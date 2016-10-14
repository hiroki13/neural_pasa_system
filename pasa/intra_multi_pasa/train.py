import sys
import time
import math
import numpy as np

from nn_utils import io_utils
from nn_utils.io_utils import dump_data, say
from ling.vocab import Vocab
from preprocessor import get_samples, theano_format
from stats.stats import corpus_statistics, sample_statistics, check_samples
from model_builder import set_model, set_train_f, set_pred_f
from eval import Eval


def train(argv):
    print '\nSETTING UP AN INTRA-SENTENTIAL TRAINING SETTING\n'

    emb = None

    """ Set labels """
    vocab_label = Vocab()
    vocab_label.set_pas_labels()
    if argv.save:
        dump_data(vocab_label, 'vocab_label')
    print '\nTARGET LABELS: %d\t%s\n' % (vocab_label.size(), str(vocab_label.w2i))

    """ Load files """
    # corpus: 1D: n_sents, 2D: n_words, 3D: (word, pas_info, pas_id)
    train_corpus, word_freqs = io_utils.load_ntc(path=argv.train_data, data_size=argv.data_size, model='word')
    print '\nTRAIN',
    corpus_statistics(train_corpus)

    if argv.dev_data:
        dev_corpus, word_freqs = io_utils.load_ntc(path=argv.dev_data, data_size=argv.data_size, model='word',
                                                   word_freqs=word_freqs)
        print '\nDEV',
        corpus_statistics(dev_corpus)

    if argv.test_data:
        test_corpus, word_freqs = io_utils.load_ntc(path=argv.test_data, data_size=argv.data_size, model='word',
                                                    word_freqs=word_freqs)
        print '\nTEST',
        corpus_statistics(test_corpus)

    """ Set vocab """
    vocab_word = Vocab()
    vocab_word.set_init_word()
    vocab_word.add_vocab(word_freqs=word_freqs, vocab_cut_off=argv.vocab_cut_off)
    if argv.save:
        dump_data(vocab_word, 'vocab_word.cut-%d' % argv.vocab_cut_off)
    print '\nVocab: %d\tType: word\n' % vocab_word.size()

    """ Preprocessing """
    # pre_samples: (x, y)
    # x: 1D: n_sents, 2D: n_prds, 3D: n_words, 4D: window + 2
    # y: 1D: n_sents, 2D: n_prds, 3D: n_words
    # word_ids: 1D: n_sents, 2D: n_words

    tr_pre_samples, tr_word_ids = get_samples(train_corpus, vocab_word, vocab_label, argv.window)
    tr_samples, train_batch_index = theano_format(tr_pre_samples)
    print '\nTRAIN',
#    sample_statistics(tr_pre_samples[1], vocab_label)
    n_train_batches = len(train_batch_index)
    print '\tTrain Mini-Batches: %d\n' % n_train_batches

    if argv.dev_data:
        dev_pre_samples, dev_word_ids = get_samples(dev_corpus, vocab_word, vocab_label, argv.window)
        dev_samples, dev_batch_index = theano_format(dev_pre_samples)
        n_dev_batches = len(dev_batch_index)
        print '\nDEV',
#        sample_statistics(dev_pre_samples[1], vocab_label)
        print '\tDev Mini-Batches: %d\n' % n_dev_batches

    if argv.test_data:
        test_pre_samples, test_word_ids = get_samples(test_corpus, vocab_word, vocab_label, argv.window)
        test_samples, test_batch_index = theano_format(test_pre_samples)
        n_test_batches = len(test_batch_index)
        print '\nTEST',
#        sample_statistics(test_pre_samples[1], vocab_label)
        print '\tTest Mini-Batches: %d\n' % n_test_batches

    if argv.check:
        check_samples(tr_pre_samples, vocab_word, vocab_label)

    ######################
    # BUILD ACTUAL MODEL #
    ######################

    """ Set a model """
    print '\n\nBuilding a model...'
    model = set_model(argv=argv, emb=emb, vocab_word=vocab_word, vocab_label=vocab_label)
    train_f = set_train_f(model, tr_samples)
    if argv.dev_data:
        dev_f = set_pred_f(model, dev_samples)
    if argv.test_data:
        test_f = set_pred_f(model, test_samples)

    ###############
    # TRAIN MODEL #
    ###############

    print '\nTRAINING START\n'

    tr_indices = range(n_train_batches)
    if argv.dev_data:
        dev_indices = range(n_dev_batches)
    if argv.test_data:
        test_indices = range(n_test_batches)

    f1_history = {}
    best_dev_f1 = -1.

    for epoch in xrange(argv.epoch):
        train_eval = Eval()
        print '\nEpoch: %d' % (epoch + 1)
        print '  TRAIN\n\t',

        np.random.shuffle(tr_indices)
        start = time.time()

        for index, b_index in enumerate(tr_indices):
            if index != 0 and index % 1000 == 0:
                print index,
                sys.stdout.flush()

            batch_range = train_batch_index[b_index]
            result_sys, result_gold, nll = train_f(index=b_index, bos=batch_range[0], eos=batch_range[1])

            assert not math.isnan(nll), 'NLL is NAN: Index: %d' % index

            train_eval.update_results(result_sys, result_gold)
            train_eval.nll += nll

        print '\n\tTime: %f' % (time.time() - start)
        train_eval.show_results()

        """ Validating """
        update = False
        if argv.dev_data:
            print '\n  DEV\n\t',
            dev_f1 = predict(dev_f, dev_batch_index, dev_indices)
            if best_dev_f1 < dev_f1:
                best_dev_f1 = dev_f1
                f1_history[epoch+1] = [best_dev_f1]
                update = True

                if argv.save:
                    dump_data(model, 'model.layer-%d.window-%d.reg-%f' % (argv.layer, argv.window, argv.reg))

        if argv.test_data:
            print '\n  TEST\n\t',
            test_f1 = predict(test_f, test_batch_index, test_indices)
            if update:
                if epoch+1 in f1_history:
                    f1_history[epoch+1].append(test_f1)
                else:
                    f1_history[epoch+1] = [test_f1]

        say('\n\n\tF1 HISTORY')
        for k, v in sorted(f1_history.items()):
            if len(v) == 2:
                say('\n\tEPOCH-{:d}  \tBEST DEV F:{:.2%}\tBEST TEST F:{:.2%}'.format(k, v[0], v[1]))
            else:
                say('\n\tEPOCH-{:d}  \tBEST DEV F:{:.2%}'.format(k, v[0]))
        say('\n\n')


def predict(f, batch_index, indices):
    pred_eval = Eval()
    start = time.time()

    for index, b_index in enumerate(indices):
        if index != 0 and index % 1000 == 0:
            print index,
            sys.stdout.flush()

        batch_range = batch_index[b_index]
        results_sys, results_gold = f(index=b_index, bos=batch_range[0], eos=batch_range[1])
        pred_eval.update_results(results_sys, results_gold)

    print '\n\tTime: %f' % (time.time() - start)
    pred_eval.show_results()

    return pred_eval.all_f1


def main(argv):
    train(argv)
