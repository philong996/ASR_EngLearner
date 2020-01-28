import datetime
import os
import codecs
import argparse
import _pickle as pickle

import speech_models
import config
import utils

import pandas as pd
import numpy as np
import tensorflow as tf
from tensorflow.keras.callbacks import ModelCheckpoint  
from tensorflow.keras import backend as K

if __name__ == "__main__":
    
    parser = argparse.ArgumentParser()

    parser.add_argument("--train", action="store_true", default=False)
    parser.add_argument("--test", action="store_true", default=False)
    parser.add_argument("--data", type=str, required=False, help='Name of data folder')
    parser.add_argument("--model", type=str, required=True, help='Name of the model to save')
    parser.add_argument("--units", type=int, required=False, default=200 , help='number of the units of RNN')
    
    args = parser.parse_args()

    # make chackpoints directory, if necessary
    if not os.path.exists('../checkpoints'):
        os.makedirs('../checkpoints')

    checkpoint_path = os.path.join('../checkpoints', args.model + '.h5')

    ROOT = '../data'
    meta = pd.read_csv(os.path.join(ROOT, args.data ,'metadata.csv'), index_col = 'index')

    data_file = os.path.join(ROOT, args.data, 'data_info.txt')
    with codecs.open(data_file , 'r') as f:
        lines = f.readlines()

    data_detail =  {
        'n_training' : int(lines[0].split(':')[-1]),
        'n_valid' : int(lines[1].split(':')[-1]),
        'n_test' : int(lines[2].split(':')[-1]),
        'max_label_length': int(lines[6].split(':')[-1]),
        'max_input_length': int(lines[5].split(':')[-1]),
        'data_folder' : lines[3].split(':')[-1].strip(),
        'num_features' : 40,
        'num_label' : 29
    }

    model = speech_models.rnn_model(input_size = (data_detail['max_input_length'], data_detail['num_features']), units = args.units)

    if args.train:

        #prepare for training data
        TRAIN_STEPS = int(data_detail['n_training'] / config.training['batch_size'])
        VALID_STEPS = int(data_detail['n_valid'] / config.training['batch_size'])
        
        train_ds = utils.get_dataset_from_tfrecords(data_detail, tfrecords_dir=data_detail['data_folder'], split='train', batch_size=config.training['batch_size'])
        valid_ds = utils.get_dataset_from_tfrecords(data_detail, tfrecords_dir=data_detail['data_folder'], split='valid', batch_size=config.training['batch_size'])

        #load weight to continue training
        if os.path.isfile(checkpoint_path):
            model.load_weights(checkpoint_path)
        
        # add checkpointer
        checkpointer = ModelCheckpoint(filepath=checkpoint_path, verbose=0) 

        #train model
        history = model.fit(train_ds, epochs = config.training['epochs'], validation_data = valid_ds, validation_steps = VALID_STEPS , steps_per_epoch = TRAIN_STEPS, callbacks= [checkpointer])

        #save the result to compare models after training
        pickle_path = os.path.join('../checkpoints', args.model + '.pickle')
        with open(pickle_path, 'wb') as f:
            pickle.dump(history.history, f)

    if args.test:

        #prepare for testing data
        TEST_STEPS = int(data_detail['n_test'] / config.training['batch_size'])

        test_ds = utils.get_dataset_from_tfrecords(data_detail, tfrecords_dir=data_detail['data_folder'], split='test', batch_size=config.training['batch_size'])

        #load model weights
        checkpoint_path = os.path.join('../checkpoints', args.model + '.h5')
        try:
            model.load_weights(checkpoint_path)
        except:
            print('There is no checkpoint file in the folder')
        
        start_time = datetime.datetime.now()

        #make predictions
        predictions = model.predict(test_ds, steps = TEST_STEPS)

        total_time = datetime.datetime.now() - start_time

        #decode predictions and save to txt file
        MAX_LABEL_LENGTH = data_detail['max_label_length']

        x_test = np.array(predictions)
        x_test_len = [MAX_LABEL_LENGTH for _ in range(len(x_test))]
        decode, log = K.ctc_decode(x_test,
                                x_test_len,
                                greedy=True,
                                beam_width=10,
                                top_paths=1)
        
        #take labels
        label_file = os.path.join(ROOT, args.data, 'labels.csv')
        df_labels = pd.read_csv(label_file)

        labels = df_labels['labels'][df_labels['split'] == 'test'].to_list()
        labels = [utils.idx_string(eval(label)) for label in labels]

        probabilities = [np.exp(x) for x in log]
        predicts = [[[int(p) for p in x if p != -1] for x in y] for y in decode]
        predicts = np.swapaxes(predicts, 0, 1)
        
        predicts = [utils.idx_string(label[0]) for label in predicts]

        if not os.path.exists('../results/'):
            os.makedirs('../results/')
        
        prediction_file = os.path.join('../results/', 'predictions_{}.txt'.format(args.model))
        with open(prediction_file, "w") as f:
            for pd, gt in zip(predicts, labels):
                f.write("Y {}\nP {}\n\n".format(gt, pd))

        #calculate metrics to assess the model
        evaluate = utils.calculate_metrics(predicts=predicts,
                                          ground_truth=labels)

        e_corpus = "\n".join([
            "Total test audios:    {}".format(len(labels)),
            "Total time:           {}\n".format(total_time),
            "Metrics:",
            "Character Error Rate: {}".format(evaluate[0]),
            "Word Error Rate:      {}".format(evaluate[1]),
            "Sequence Error Rate:  {}".format(evaluate[2]),
        ])
        
        evaluate_file = os.path.join('../results/', "evaluate_{}.txt".format(args.model))
        with open(evaluate_file, "w") as ev_f:
            ev_f.write(e_corpus)
            print(e_corpus)
