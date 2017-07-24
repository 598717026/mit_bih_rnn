#!/usr/bin/env python
from __future__ import print_function

import numpy as np
import cPickle as pickle
import os
import functools
import tensorflow as tf
import sys
from Hlookup import cluster

np.set_printoptions(threshold=np.nan)

script_path = os.path.dirname(os.path.realpath(__file__))

data_path = ''.join([script_path, "/mit_bih_delight.pkl"])

mcmc_train_x_path = ''.join([script_path, "/mcmc_data/mcmc_train_x0.dat"])
mcmc_train_y_path = ''.join([script_path, "/mcmc_data/mcmc_train_y0.dat"])

mcmc_test_x_path = ''.join([script_path, "/mcmc_data/mcmc_test_x1.dat"])
mcmc_test_y_path = ''.join([script_path, "/mcmc_data/mcmc_test_y1.dat"])

if len(sys.argv) > 1:
	_base_save_path = sys.argv[1]

else:
	_base_save_path = ''.join([script_path, '/logs/vars/tmp/model.ckpt'])

_cluster_path = ''.join([_base_save_path, '.clustered'])

_dict_path = ''.join([script_path, '/mit_bih_delight_dict.pkl'])

data_file = open(data_path, 'r')

data = pickle.load(data_file)

data_file.close()

window_length = 10

window_skip = 1

no_features = window_length * len(data[0][0][0])

no_epochs = 400
no_centroids = 4
no_macro_epochs = 2

#Non-patient-specific-training error target from state-of-the-art of 2017: http://ieeexplore.ieee.org/document/7893269/
error_target = 1.0
clustered_error_target = 2.0

def feed_windows(_data, _window_skip, _window_len, _features_per_step):
    data_seq = np.zeros((len(_data),_window_len*_features_per_step))
    window_start_index = 0
    window_end_index = window_start_index+_window_len
    in_seq_index = 0
    while window_end_index < len(_data):
        data_window = _data[window_start_index:window_end_index].flatten()
        data_seq[in_seq_index] = data_window
        in_seq_index+=1
        window_start_index+=_window_skip
        window_end_index+=_window_skip
    return data_seq

data_train_or_test = data[2]

no_train = len(data_train_or_test)-np.sum(data_train_or_test)
no_test = np.sum(data_train_or_test)

true_data = [[np.zeros((no_train, len(data[0][0]), no_features),dtype=np.float32), np.zeros((no_train, len(data[1][0])),dtype=np.float32)],[np.zeros((no_test, len(data[0][0]), no_features),dtype=np.float32), np.zeros((no_test, len(data[1][0])),dtype=np.float32)]]

print("no_train: ",no_train,"\nno_test: ",no_test)

test_index = 0
train_index = 0

for i in range(len(data_train_or_test)):
	if data_train_or_test[i]:
		true_data[1][0][test_index] = feed_windows(data[0][i],window_skip,window_length,len(data[0][0][0]))
		true_data[1][1][test_index] = data[1][i]
		test_index+=1
	else:
		true_data[0][0][train_index] = feed_windows(data[0][i],window_skip,window_length,len(data[0][0][0]))
                true_data[0][1][train_index] = data[1][i]
                train_index+=1

delight_threshold = 0.5

max_b_length = no_features/10

delight_data_train_x = true_data[0][0].reshape((true_data[0][0].shape[0]*true_data[0][0].shape[1],true_data[0][0].shape[2]))

delight_b = np.zeros((max_b_length,no_features),dtype=np.float32)

delight_b_vacancy = True

b_alternatives = np.zeros((max_b_length, max_b_length, no_features), dtype=np.float32)

b_alt_errors = np.zeros((max_b_length+1), dtype=np.float32)

def delight_error(anew, b):
   return np.square(np.subtract(np.matmul(np.matmul(np.matmul(b, np.linalg.pinv(np.matmul(b.T, b))),b.T), anew), anew)).sum()/np.square(anew).sum()

for i in range(len(delight_data_train_x)):
    if max(delight_data_train_x[i]) > 0.0:
        if not delight_b_vacancy:
            for j in range(max_b_length):
                b_alternatives[j] = delight_b
                b_alternatives[j][j] = delight_data_train_x[i]
        for j in range(max_b_length):
            if delight_b_vacancy:
                if j == max_b_length-1:
                    delight_b_vacancy = False
                if max(delight_b[j]) == 0.0:
                    delight_b[j] = delight_data_train_x[i]
                    break
            else:
                b_alt_errors[j] = delight_error(delight_data_train_x[i].reshape((1,delight_data_train_x[i].shape[0])).transpose(),b_alternatives[j].T)
		if not delight_b_vacancy:
			b_alt_errors[max_b_length] = delight_error(delight_data_train_x[i].reshape((1,delight_data_train_x[i].shape[0])).transpose(),delight_b.T)
			if np.argmin(b_alt_errors) != max_b_length and b_alt_errors[max_b_length] > delight_threshold:
				delight_b = b_alternatives[np.argmin(b_alt_errors)]
dict_save = open(_dict_path, "w")

pickle.dump(delight_b, dict_save)

dict_save.close()

def lazy_property(function):
    attribute = '_' + function.__name__

    @property
    @functools.wraps(function)
    def wrapper(self):
        if not hasattr(self, attribute):
            setattr(self, attribute, function(self))
        return getattr(self, attribute)
    return wrapper


def grad_fixed(grad,encoding):
	#this function takes gradient and encoding, it returns the average gradients for each encoding
	n_clusters=np.max(encoding)+1
	masks=[]
	for enc in range(n_clusters):
		inds=np.where(encoding == enc)
		w=np.zeros(encoding.shape,dtype=np.float32)
		w[inds]=1
		masks.append(tf.constant(w))
	inds=np.asarray(np.where(encoding == 0)).transpose()
	gg=tf.gather_nd(grad,indices=inds)
	gg=tf.reduce_mean(gg)
	out_grad=gg*masks[0]
	for enc in range(1,n_clusters):
		inds=np.asarray(np.where(encoding == enc)).transpose()
		gg=tf.gather_nd(grad,indices=inds)
		gg=tf.reduce_mean(gg)
		out_grad=out_grad+gg*masks[enc]
        print("out_grad: ", out_grad, "\ngrad", grad)
	return out_grad


# Class definition modified from Danijar Hafner's example at https://gist.github.com/danijar/3f3b547ff68effb03e20c470af22c696
class VariableSequenceClassificationSharedWeights:

    def __init__(self, data, target, delight_dict, num_hidden=150, num_layers=2, num_fc=2, fc_len=20):
        self.data = data
        self.target = target
        self._num_hidden = num_hidden
        self._num_layers = num_layers
        self._num_fc = num_fc
        self._fc_len = fc_len
        self._delight_dict = delight_dict
        self.encodings = {}
        self.new_grads = []
        self.prediction
        self.error
        self.optimize
        self.optimizer
        self.delight_dict_tensor

    @lazy_property
    def length(self):
        used = tf.sign(tf.reduce_max(tf.abs(self.data), axis=2))
        length = tf.reduce_sum(used, axis=1)
        length = tf.cast(length, tf.int32)
        return length

    @lazy_property
    def delight_dict_tensor(self):
        return tf.convert_to_tensor(self._delight_dict, dtype=tf.float32)

    @lazy_property
    def prediction(self):
        subcells = []
        true_data = tf.matmul(self.data, self.delight_dict_tensor)
        for i in range(self._num_layers):
                if i == 0 and self._num_layers > 1:
                    #Dropout added below LSTM layer only, in accordance with http://ieeexplore.ieee.org/document/7333848/?reload=true
                    subcells.append(tf.nn.rnn_cell.DropoutWrapper(tf.nn.rnn_cell.LSTMCell(self._num_hidden, initializer=tf.contrib.layers.xavier_initializer()), input_keep_prob = 0.8))
                else:
                    subcells.append(tf.nn.rnn_cell.LSTMCell(self._num_hidden, initializer = tf.contrib.layers.xavier_initializer()))
        main_cell = tf.nn.rnn_cell.MultiRNNCell(subcells, state_is_tuple=True)
        # Recurrent network.
        output, _ = tf.nn.dynamic_rnn(
            main_cell,
            true_data,
            dtype=tf.float32,
            sequence_length=self.length,
        )
        last = self._last_relevant(output, self.length)
        if self._num_fc == 0:
            last_before_softmax = last
            out_num = self._num_hidden
        else:
            fc_layers = []
            if self._num_fc == 1:
                fc_layers.append(tf.contrib.layers.fully_connected(last, self._fc_len))
            else:
                fc_layers.append(tf.contrib.layers.fully_connected(last, self._fc_len, activation_fn=tf.nn.sigmoid))
                for l in range(1, self._num_fc-1):
                    fc_layers.append(tf.contrib.layers.fully_connected(fc_layers[l-1], self._fc_len, activation_fn=tf.nn.sigmoid))
                fc_layers.append(tf.contrib.layers.fully_connected(fc_layers[self._num_fc-2], self._fc_len))
            last_before_softmax = fc_layers[self._num_fc-1]
            out_num = self._fc_len

        # Softmax layer.
        weight, bias = self._weight_and_bias(
            out_num, int(self.target.get_shape()[1]))
        prediction = tf.nn.softmax(tf.matmul(last_before_softmax, weight) + bias)
	prediction = tf.clip_by_value(prediction, 1e-3, 1.0-1e-3)
        return prediction

    @lazy_property
    def cost(self):
        cross_entropy = -tf.reduce_sum(self.target * tf.log(self.prediction))
        return cross_entropy

    @lazy_property
    def optimizer(self):
        learning_rate = 0.01
        momentum = 0.0
        optimizer = tf.train.RMSPropOptimizer(learning_rate)
        return optimizer

    @lazy_property
    def optimize(self):
        return self.optimizer.minimize(self.cost)

    @lazy_property
    def grads(self):
        return self.optimizer.compute_gradients(self.cost)

    @lazy_property
    def optimize_ws(self):
        for pair in self.grads:
            if pair[1].name in self.encodings:
                self.new_grads.append((grad_fixed(pair[0],self.encodings[pair[1].name]),pair[1]))
            else:
                self.new_grads.append(pair)
        return self.optimizer.apply_gradients(self.new_grads)

    @lazy_property
    def error(self):
        mistakes = tf.not_equal(
            tf.argmax(self.target, 1), tf.argmax(self.prediction, 1))
        return tf.reduce_mean(tf.cast(mistakes, tf.float32))

    @staticmethod
    def _weight_and_bias(in_size, out_size):
        weight = tf.get_variable("weight", shape=[in_size,out_size], initializer=tf.contrib.layers.xavier_initializer())
        bias = tf.constant(0.1, shape=[out_size], dtype=tf.float32)
        return weight, tf.Variable(bias)

    @staticmethod
    def _last_relevant(output, length):
        batch_size = tf.shape(output)[0]
        max_length = int(output.get_shape()[1])
        output_size = int(output.get_shape()[2])
        index = tf.range(0, batch_size) * max_length + (length - 1)
        flat = tf.reshape(output, [-1, output_size])
        relevant = tf.gather(flat, index)
        return relevant




if __name__ == '__main__':
    all_data = true_data
    train = all_data[0]
    test = all_data[1]
    conf_weights =  np.sum(test[1], axis=0)
    batch_size = 200
    no_examples, rows, row_size = train[0].shape
    num_classes = len(train[1][0])
    no_batches = no_examples/batch_size
    data = tf.placeholder(tf.float32, [None, rows, row_size])
    target = tf.placeholder(tf.float32, [None, num_classes])
    model = VariableSequenceClassificationSharedWeights(data, target, delight_dict=delight_b.T)
    sess = tf.Session()
    sess.run(tf.global_variables_initializer())

    print(test[0].shape,test[1].shape)
    saver = tf.train.Saver()

    # Implementing random weight sharing as described in https://arxiv.org/pdf/1504.04788.pdf
    for macro_epoch in range(no_macro_epochs):
        _save_path = ''.join([_base_save_path, '-', str(macro_epoch+1)])
        if macro_epoch == 0:
            for epoch in range(no_epochs):
                error_sum = 0.0
                for i in range(no_batches):
                    batch_data = train[0][i*batch_size:(i+1)*batch_size]
                    batch_target = train[1][i*batch_size:(i+1)*batch_size]
                    sess.run(model.optimize, feed_dict={data: batch_data, target: batch_target})
                    train_error = sess.run(model.error, feed_dict={data:batch_data, target: batch_target})
                    error_sum+=100*train_error
                    print('Macro-Epoch {:2d} Epoch {:2d} train batch {:2d} error {:3.1f}% cumulative error {:3.1f}%'.format(macro_epoch+1, epoch+1, i+1, 100*train_error, error_sum/(float(i+1))))
                if (epoch+1)%5 == 0 or error_sum/no_batches <= error_target:
                    save_path = saver.save(sess, _save_path, global_step=epoch+1)
                    print("Model vars saved in file: %s" % save_path)
                if error_sum/no_batches <= error_target:
                    break

            tvars = tf.trainable_variables()
            tvars_vals = sess.run(tvars)
            for var, val in zip(tvars, tvars_vals):
                print(var.name, type(val))
                if not 'bias' in var.name:
                    clu = cluster(no_centroids, val)
                    newval_keys, newvals = clu.tree_search_nn(val)
                    true_newvals = np.zeros((len(newval_keys)), dtype=np.float32)
                    for i in range(len(newval_keys)):
                        true_newvals[i] = newvals[newval_keys[i]]
                    var.assign(np.reshape(true_newvals,val.shape)).eval(session = sess)
                    model.encodings[var.name] = np.reshape(newval_keys, val.shape)
                    del clu
            cluster_save_path = saver.save(sess, _cluster_path, global_step=macro_epoch+1)
            print("Shared-weight model vars saved in file: %s" % cluster_save_path)
            error_sum = 0.0
            for i in range(no_batches):
                batch_data = train[0][i*batch_size:(i+1)*batch_size]
                batch_target = train[1][i*batch_size:(i+1)*batch_size]
                error = sess.run(model.error, feed_dict = {data:batch_data, target:batch_target})
                error_sum+=100*error
                print('Macro-Epoch {:2d} Batch {:2d} shared-weight error {:3.1f}% cumulative error {:3.1f}%'.format(macro_epoch+1, i+1, 100*error, error_sum/(float(i+1))))
            if error_sum/no_batches <= clustered_error_target:
                break

        else:
            for epoch in range(no_epochs):
                error_sum = 0.0
                for i in range(no_batches):
                    batch_data = train[0][i*batch_size:(i+1)*batch_size]
                    batch_target = train[1][i*batch_size:(i+1)*batch_size]
                    sess.run(model.optimize_ws, feed_dict={data: batch_data, target: batch_target})
                    train_error = sess.run(model.error, feed_dict={data:batch_data, target: batch_target})
                    error_sum+=100*train_error
                    print('Macro-Epoch (shared-weight) {:2d} Epoch {:2d} train batch {:2d} error {:3.1f}% cumulative error {:3.1f}%'.format(macro_epoch+1, epoch+1, i+1, 100*train_error, error_sum/(float(i+1))))
                if (epoch+1)%5 == 0 or error_sum/no_batches <= error_target:
                    save_path = saver.save(sess, _save_path, global_step=epoch+1)
                    print("Model vars saved in file: %s" % save_path)
                if error_sum/no_batches <= error_target:
                    break
