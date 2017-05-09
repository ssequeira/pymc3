from itertools import combinations
import numpy as np
from numpy.testing import assert_almost_equal

try:
    import unittest.mock as mock  # py3
except ImportError:
    import mock

import pymc3 as pm
import theano.tensor as tt
from theano import shared
from .models import simple_init
from .helpers import SeededTest

# Test if multiprocessing is available
import multiprocessing
import pytest
try:
    multiprocessing.Pool(2)
except:
    pass


class TestSample(SeededTest):
    def setup_method(self):
        super(TestSample, self).setup_method()
        self.model, self.start, self.step, _ = simple_init()

    def test_sample_does_not_set_seed(self):
        random_numbers = []
        for _ in range(2):
            np.random.seed(1)
            with self.model:
                pm.sample(1, tune=0)
                random_numbers.append(np.random.random())
        assert random_numbers[0] == random_numbers[1]

    def test_parallel_sample_does_not_reuse_seed(self):
        njobs = 4
        random_numbers = []
        draws = []
        for _ in range(2):
            np.random.seed(1)  # seeds in other processes don't effect main process
            with self.model:
                trace = pm.sample(100, tune=0, njobs=njobs)
            # numpy thread mentioned race condition.  might as well check none are equal
            for first, second in combinations(range(njobs), 2):
                first_chain = trace.get_values('x', chains=first)
                second_chain = trace.get_values('x', chains=second)
                assert not (first_chain == second_chain).all()
            draws.append(trace.get_values('x'))
            random_numbers.append(np.random.random())

        # Make sure future random processes aren't effected by this
        assert random_numbers[0] == random_numbers[1]
        assert (draws[0] == draws[1]).all()

    def test_sample(self):
        test_njobs = [1]
        with self.model:
            for njobs in test_njobs:
                for steps in [1, 10, 300]:
                    pm.sample(steps, tune=0, step=self.step, njobs=njobs, random_seed=self.random_seed)

    def test_sample_init(self):
        with self.model:
            for init in ('advi', 'advi_map', 'map', 'nuts'):
                pm.sample(init=init, tune=0,
                          n_init=1000, draws=50,
                          random_seed=self.random_seed)


    def test_sample_args(self):
        with self.model:
            with pytest.raises(TypeError) as excinfo:
                pm.sample(50, tune=0, init=None, step_kwargs={'nuts': {'foo': 1}})
            assert "'foo'" in str(excinfo.value)

            with pytest.raises(ValueError) as excinfo:
                pm.sample(50, tune=0, init=None, step_kwargs={'foo': {}})
            assert 'foo' in str(excinfo.value)

            pm.sample(10, tune=0, init=None, nuts_kwargs={'target_accept': 0.9})

            with pytest.raises(ValueError) as excinfo:
                pm.sample(5, tune=0, init=None, step_kwargs={}, nuts_kwargs={})
            assert 'Specify only one' in str(excinfo.value)

    def test_iter_sample(self):
        with self.model:
            samps = pm.sampling.iter_sample(draws=5, step=self.step,
                                            start=self.start, tune=0,
                                            random_seed=self.random_seed)
            for i, trace in enumerate(samps):
                assert i == len(trace) - 1, "Trace does not have correct length."

    def test_parallel_start(self):
        with self.model:
            tr = pm.sample(0, tune=5, njobs=2,
                           discard_tuned_samples=False,
                           start=[{'x': [10, 10]}, {'x': [-10, -10]}],
                           random_seed=self.random_seed)
        assert tr.get_values('x', chains=0)[0][0] > 0
        assert tr.get_values('x', chains=1)[0][0] < 0

    def test_sample_tune_len(self):
        with self.model:
            trace = pm.sample(draws=100, tune=50, njobs=1)
            assert len(trace) == 100
            trace = pm.sample(draws=100, tune=50, njobs=1,
                              discard_tuned_samples=False)
            assert len(trace) == 150
            trace = pm.sample(draws=100, tune=50, njobs=4)
            assert len(trace) == 100


class SoftUpdate(SeededTest):
    def test_soft_update_all_present(self):
        start = {'a': 1, 'b': 2}
        test_point = {'a': 3, 'b': 4}
        pm.sampling._soft_update(start, test_point)
        assert start == {'a': 1, 'b': 2}

    def test_soft_update_one_missing(self):
        start = {'a': 1, }
        test_point = {'a': 3, 'b': 4}
        pm.sampling._soft_update(start, test_point)
        assert start == {'a': 1, 'b': 4}

    def test_soft_update_empty(self):
        start = {}
        test_point = {'a': 3, 'b': 4}
        pm.sampling._soft_update(start, test_point)
        assert start == test_point

    def test_soft_update_transformed(self):
        start = {'a': 2}
        test_point = {'a_log__': 0}
        pm.sampling._soft_update(start, test_point)
        assert assert_almost_equal(start['a_log__'], np.log(start['a']))


class TestNamedSampling(SeededTest):
    def test_shared_named(self):
        G_var = shared(value=np.atleast_2d(1.), broadcastable=(True, False),
                       name="G")

        with pm.Model():
            theta0 = pm.Normal('theta0', mu=np.atleast_2d(0),
                               tau=np.atleast_2d(1e20), shape=(1, 1),
                               testval=np.atleast_2d(0))
            theta = pm.Normal('theta', mu=tt.dot(G_var, theta0),
                              tau=np.atleast_2d(1e20), shape=(1, 1))
            res = theta.random()
            assert np.isclose(res, 0.)

    def test_shared_unnamed(self):
        G_var = shared(value=np.atleast_2d(1.), broadcastable=(True, False))
        with pm.Model():
            theta0 = pm.Normal('theta0', mu=np.atleast_2d(0),
                               tau=np.atleast_2d(1e20), shape=(1, 1),
                               testval=np.atleast_2d(0))
            theta = pm.Normal('theta', mu=tt.dot(G_var, theta0),
                              tau=np.atleast_2d(1e20), shape=(1, 1))
            res = theta.random()
            assert np.isclose(res, 0.)

    def test_constant_named(self):
        G_var = tt.constant(np.atleast_2d(1.), name="G")
        with pm.Model():
            theta0 = pm.Normal('theta0', mu=np.atleast_2d(0),
                               tau=np.atleast_2d(1e20), shape=(1, 1),
                               testval=np.atleast_2d(0))
            theta = pm.Normal('theta', mu=tt.dot(G_var, theta0),
                              tau=np.atleast_2d(1e20), shape=(1, 1))

            res = theta.random()
            assert np.isclose(res, 0.)



class TestChooseBackend(object):
    def test_choose_backend_none(self):
        with mock.patch('pymc3.sampling.NDArray') as nd:
            pm.sampling._choose_backend(None, 'chain')
        assert nd.called

    def test_choose_backend_list_of_variables(self):
        with mock.patch('pymc3.sampling.NDArray') as nd:
            pm.sampling._choose_backend(['var1', 'var2'], 'chain')
        nd.assert_called_with(vars=['var1', 'var2'])

    def test_choose_backend_invalid(self):
        with pytest.raises(ValueError):
            pm.sampling._choose_backend('invalid', 'chain')

    def test_choose_backend_shortcut(self):
        backend = mock.Mock()
        shortcuts = {'test_backend': {'backend': backend,
                                      'name': None}}
        pm.sampling._choose_backend('test_backend', 'chain', shortcuts=shortcuts)
        assert backend.called
