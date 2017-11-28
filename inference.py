# -*- coding: utf-8 -*-

#Author: Jay Yip
#Date 22Mar2017


"""Inference"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf
import pickle
import os
from hanziconv.hanziconv import HanziConv

from ops import input_ops
from ops.vocab import Vocabulary
import configuration
from lstm_based_cws_model import LSTMCWS



tf.flags.DEFINE_string("input_file_dir", "data/download_dir/icwb2-data/gold/",
                       "Path of input files.")
tf.flags.DEFINE_string("vocab_dir", "data/download_dir/vocab.pkl",
                       "Path of vocabulary file.")
tf.flags.DEFINE_string("train_dir", "save_model",
                       "Directory for saving and loading model checkpoints.")
tf.flags.DEFINE_string("out_dir", 'output',
                        "Frequency at which loss and global step are logged.")

FLAGS = tf.app.flags.FLAGS

def _create_restore_fn(checkpoint_path, saver):
    """Creates a function that restores a model from checkpoint.

    Args:
      checkpoint_path: Checkpoint file or a directory containing a checkpoint
        file.
      saver: Saver for restoring variables from the checkpoint file.

    Returns:
      restore_fn: A function such that restore_fn(sess) loads model variables
        from the checkpoint file.
 
    Raises:
      ValueError: If checkpoint_path does not refer to a checkpoint file or a
        directory containing a checkpoint file.
    """
    if tf.gfile.IsDirectory(checkpoint_path):
        checkpoint_path = tf.train.latest_checkpoint(checkpoint_path)
        if not checkpoint_path:
            raise ValueError("No checkpoint file found in: %s" % checkpoint_path)

    def _restore_fn(sess):
        tf.logging.info("Loading model from checkpoint: %s", checkpoint_path)
        saver.restore(sess, checkpoint_path)
        tf.logging.info("Successfully loaded checkpoint: %s",
                        os.path.basename(checkpoint_path))

    return _restore_fn

def insert_space(char, tag):
    if tag == 0 or tag == 3:
        return char + ' '
    else:
        return char

def get_final_output(line, predict_tag):
    return ''.join([insert_space(char, tag) for char, tag in zip(line, predict_tag)])

def append_to_file(output_buffer, filename):
    filename = os.path.join(FLAGS.out_dir, 'out_' + os.path.split(filename)[-1])

    if os.path.exists(filename):
        append_write = 'ab' # append if already exists
    else:
        append_write = 'wb' # make a new file if not

    with open(filename, append_write) as file:
        for item in output_buffer:
            file.write(item.encode('utf8')+ b'\n')

def tag_to_id(t):
    if t == 's':
        return 0

    elif t == 'b':
        return 1

    elif t == 'm':
        return 2

    elif t == 'e':
        return 3

def seq_acc(seq1, seq2):
    correct = 0
    if len(seq1) != len(seq2):
        print('Not equal seq length')
        print(seq1)
        print(seq2)
        raise ValueError

    for seq_ind, char in enumerate(seq1):
        if char == seq2[seq_ind]:
            correct += 1
    
    return correct

def main(unused_argv):

    #Preprocess before building graph
    #Read vocab file
    with open(FLAGS.vocab_dir, 'rb') as f:
        u = pickle._Unpickler(f)
        u.encoding = 'latin1'
        p = u.load()

    if not tf.gfile.IsDirectory(FLAGS.out_dir):
        tf.logging.info('Create Output dir as %s', FLAGS.out_dir)
        tf.gfile.MakeDirs(FLAGS.out_dir)

    filename_list = []
    for dirpath, dirnames, filenames in os.walk(FLAGS.input_file_dir):
        for filename in filenames:
            fullpath = os.path.join(dirpath, filename)
            if fullpath.split('.')[-1] in ['utf8'] and 'test' in fullpath:
                filename_list.append(fullpath)

    checkpoint_path = FLAGS.train_dir

    model_config = configuration.ModelConfig()


    #Create possible tags for fast lookup
    possible_tags = []
    for i in range(1, 300):
        if i == 1:
            possible_tags.append('s')
        else:
            possible_tags.append('b' + 'm' * (i - 2) + 'e')

    #Build graph for inference
    g = tf.Graph()
    with g.as_default():

        input_seq_feed = tf.placeholder(name = 'input_seq_feed', dtype = tf.int64)

        #Add transition var to graph
        with tf.variable_scope('tag_inf') as scope:
            transition_param = tf.Variable(name = 'transitions', 
                initial_value = 0,
                validate_shape=False)

        #Build model
        model = LSTMCWS(model_config, 'inference')
        print('Building model...')
        model.build()



    with tf.Session(graph=g) as sess:

        #Restore ckpt
        saver = tf.train.Saver()
        restore_fn = _create_restore_fn(checkpoint_path, saver)
        restore_fn(sess)


        for filename in filename_list:
            output_buffer = []
            num_correct = 0
            num_total = 0
            proc_fn = input_ops.get_process_fn(filename)
            with tf.gfile.GFile(filename, 'rb') as f:
                for line in f:
                    l = proc_fn(line)
                    input_seqs_list = [p.word_to_id(x) for x in ''.join(l)]

                    #get seqence label
                    #str_input_seqs_list = [str(x) for x in input_seqs_list]
                    input_label = []
                    for w in l:
                        if len(w) > 0 and len(w) <= 299:
                            input_label.append(possible_tags[len(w)-1])
                        elif len(w) == 0:
                            pass
                        else:
                            input_label.append('s')

                    str_input_label = ''.join(input_label)
                    input_label = [tag_to_id(x) for x in str_input_label]


                    #get input sequence
                    input_seqs_list = [x for x in input_seqs_list if x != 1]


                    if len(input_seqs_list) <= 1:
                        predict_tag = [0]
                        output_buffer.append(get_final_output(l, predict_tag))

                    else:
                        predict_tag = sess.run(model.predict_tag, 
                            feed_dict = {input_seq_feed:input_seqs_list})

                        if len(predict_tag) != len(input_seqs_list):
                            print('predict not right')
                            print(l)
                        if len(input_seqs_list) != len(input_label):
                            print('label not right')
                            print(l)
                            print(str_input_label)

                        output_buffer.append(get_final_output(l, predict_tag))

                        num_correct += seq_acc(input_label, predict_tag)
                        num_total += len(input_label)

                    if len(output_buffer) >= 1000:
                        append_to_file(output_buffer, filename)
                        output_buffer = []

                if output_buffer:
                    append_to_file(output_buffer, filename)

            print('%s Acc: %f' % (filename, num_correct / num_total))
            print('%s Correct: %d' % (filename, num_correct))
            print('%s Total: %d' % (filename, num_total))

if __name__ == '__main__':
    tf.app.run()
