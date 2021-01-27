# -*- coding: utf-8 -*-

import os
import sys
import re
import time
import math
import argparse
import pickle
from functools import partial
from multiprocessing import Pool, cpu_count
from collections import namedtuple
import logging
logger = logging.getLogger('pymc3')
logger.setLevel(logging.ERROR)

import h5py
import numpy as np
# np.seterr(all='raise')
import scipy
import pandas as pd
from tqdm import tqdm
import torch
torch.manual_seed(0)
# torch.autograd.set_detect_anomaly(True)
import pyro
import jax
import jax.numpy as jnp
import numpyro
from jax import lax
import arviz
import pymc3
import pystan
import matplotlib.pyplot as plt

import wf_func as wff

pyro.set_rng_seed(0)

global_start = time.time()
cpu_global_start = time.process_time()

psr = argparse.ArgumentParser()
psr.add_argument('-o', dest='opt', type=str, help='output file')
psr.add_argument('ipt', type=str, help='input file')
psr.add_argument('--met', type=str, help='fitting method')
psr.add_argument('--ref', type=str, nargs='+', help='reference file')
psr.add_argument('-N', '--Ncpu', dest='Ncpu', type=int, default=50)
args = psr.parse_args()

fipt = args.ipt
fopt = args.opt
reference = args.ref
method = args.met

use_cuda = False

if use_cuda:
    device = torch.device(0)
    torch.cuda.init()
    torch.cuda.empty_cache()
else:
    device = torch.device('cpu')

spe_pre = wff.read_model(reference[0])
with h5py.File(fipt, 'r', libver='latest', swmr=True) as ipt:
    ent = ipt['Readout/Waveform'][:]
    N = len(ent)
    print('{} waveforms will be computed'.format(N))
    window = len(ent[0]['Waveform'])
    assert window >= len(spe_pre[0]['spe']), 'Single PE too long which is {}'.format(len(spe_pre[0]['spe']))
    Mu = ipt['Readout/Waveform'].attrs['mu'].item()
    Tau = ipt['Readout/Waveform'].attrs['tau'].item()
    Sigma = ipt['Readout/Waveform'].attrs['sigma'].item()
    pelist = ipt['SimTriggerInfo']['PEList'][:]
    start = ipt['SimTruth/T'][:]

gmu = 160.
gsigma = 40.
p = [8., 0.5, 24.]
p[2] = (p[2] * gmu / np.sum(wff.spe(np.arange(window), tau=p[0], sigma=p[1], A=p[2]))).item()
if Tau != 0:
    Alpha = 1 / Tau
    Co = (Alpha / 2. * np.exp(Alpha ** 2 * Sigma ** 2 / 2.)).item()
std = 1.

def time_pyro(a0, a1):
    stime = np.empty(a1 - a0)
    tlist = torch.arange(window).to(device)
    t_auto = (tlist[:, None] - tlist).to(device)
    # amplitude to voltage converter
    AV = (p[2] * torch.exp(-1 / 2 * torch.pow((torch.log((t_auto + torch.abs(t_auto)) * (1 / p[0] / 2)) * (1 / p[1])), 2))).to(device)
    Amu = torch.tensor((0., 1.)).expand(window, 2).to(device)
    Asigma = torch.tensor((std / gsigma, gsigma / gmu)).expand(window, 2).to(device)
    wmu = torch.tensor(0.).to(device)
    wsigma = torch.tensor(std).to(device)
    left = torch.tensor(0.).to(device)
    right = torch.tensor(float(window)).to(device)
    def model(y, mu):
        t0 = pyro.sample('t0', pyro.distributions.Uniform(left, right)).to(device)
        if Tau == 0:
            light_curve = pyro.distributions.Normal(t0, scale=Sigma)
            pl = (torch.exp(light_curve.log_prob(tlist)) * mu).to(device)
        else:
            pl = (Co * (1. - torch.erf((Alpha * Sigma ** 2 - (tlist - t0)) / (math.sqrt(2.) * Sigma))) * torch.exp(-Alpha * (tlist - t0)) * mu).to(device)
        A = pyro.sample('A', pyro.distributions.MixtureSameFamily(
            pyro.distributions.Categorical(torch.stack((1 - pl, pl)).T.to(device)),
            pyro.distributions.Normal(Amu, Asigma)
        ))
        with pyro.plate('observations', window):
            obs = pyro.sample('obs', pyro.distributions.Normal(wmu, scale=wsigma), obs=y-torch.matmul(AV, A)).to(device)
        return obs
    nuts_kernel = pyro.infer.mcmc.NUTS(model, jit_compile=True)
    mcmc = pyro.infer.mcmc.api.MCMC(nuts_kernel, num_samples=1000, warmup_steps=500, num_chains=1)
    for i in range(a0, a1):
        wave = torch.from_numpy(ent[i]['Waveform'].astype(np.float32)).to(device)
        mu=1 / gmu * torch.sum(wave)
        mcmc.run(y=wave, mu=mu)
        stime[i - a0] = np.mean(mcmc.get_samples()['t0'].cpu().numpy())
    return stime

class mNormal(numpyro.distributions.distribution.Distribution):
    arg_constraints = {'pl': numpyro.distributions.constraints.real}
    support = numpyro.distributions.constraints.real
    reparametrized_params = ['pl']

    def __init__(self, pl, s, mu, sigma, validate_args=None):
        self.pl = pl
        self.s = s
        self.mu = mu
        self.sigma = sigma
        self.norm0 = numpyro.distributions.Normal(loc=0., scale=self.s)
        self.norm1 = numpyro.distributions.Normal(loc=self.mu, scale=self.sigma)
        super(mNormal, self).__init__(batch_shape=jnp.shape(pl), validate_args=validate_args)

    @numpyro.distributions.util.validate_sample
    def log_prob(self, value):
        prob0 = self.norm0.log_prob(value)
        prob1 = self.norm1.log_prob(value)
        # return jnp.log(jnp.clip((1 - self.pl) * jnp.exp(prob0) + self.pl * jnp.exp(prob1), jnp.finfo(jnp.float32).tiny, jnp.inf))
        # return jnp.where(self.pl > jnp.finfo(jnp.float32).resolution, jax.scipy.special.logsumexp(prob, axis=0, b=pl), prob0)
        prob = jnp.vstack([prob0, prob1])
        pl = jnp.vstack([(1 - self.pl), self.pl])
        return jax.scipy.special.logsumexp(prob, axis=0, b=pl)

def time_numpyro(a0, a1):
    init = namedtuple('ParamInfo', ['z', 'potential_energy', 'z_grad'])
    rng_key = jax.random.PRNGKey(1)
    rng_key, rng_key_ = jax.random.split(rng_key)
    stime = np.empty(a1 - a0)
    tlist = jnp.arange(window)
    t_auto = tlist[:, None] - tlist
    # amplitude to voltage converter
    AV = p[2] * jnp.exp(-1 / 2 * jnp.power((jnp.log((t_auto + jnp.abs(t_auto)) * (1 / p[0] / 2)) * (1 / p[1])), 2))
    def model(y, mu):
        t0 = numpyro.sample('t0', numpyro.distributions.Uniform(0., float(window)))
        if Tau == 0:
            light_curve = numpyro.distributions.Normal(t0, scale=Sigma)
            pl = numpyro.primitives.deterministic('pl', jnp.exp(light_curve.log_prob(tlist)) * mu + jnp.finfo(jnp.float32).resolution)
        else:
            pl = numpyro.primitives.deterministic('pl', Co * (1. - jax.scipy.special.erf((Alpha * Sigma ** 2 - (tlist - t0)) / (math.sqrt(2.) * Sigma))) * jnp.exp(-Alpha * (tlist - t0)) * mu + jnp.finfo(jnp.float32).resolution)
        A = numpyro.sample('A', mNormal(pl, std / gsigma, 1., gsigma / gmu))
        with numpyro.plate('observations', window):
            obs = numpyro.sample('obs', numpyro.distributions.Normal(jnp.matmul(AV, A), scale=std), obs=y)
        return obs
    nuts_kernel = numpyro.infer.NUTS(model, adapt_step_size=True)
    mcmc = numpyro.infer.MCMC(nuts_kernel, num_samples=1000, num_warmup=500, num_chains=1, jit_model_args=True)
    for i in range(a0, a1):
        cid = ent[i]['ChannelID']
        wave = jnp.array(ent[i]['Waveform'].astype(np.float32))
        mu = jnp.sum(wave) / gmu
        A = jnp.hstack([jnp.where(wave > spe_pre[cid]['std'] * 5, wave, 0)[spe_pre[cid]['mar_l']:], jnp.zeros(spe_pre[cid]['mar_l'])])
        A = A / jnp.sum(A) * mu
        t0 = jnp.clip(jnp.argmax(wave) * spe_pre[cid]['epulse'] - spe_pre[cid]['mar_l'], 0, window).astype(jnp.float32)
        potential = lambda z: numpyro.infer.util.potential_energy(model=model, model_args=(wave, mu), model_kwargs={}, params=z)
        initp = init(z={'t0':t0, 'A':A}, potential_energy=potential({'t0':t0, 'A':A}), z_grad=jax.grad(potential)({'t0':t0, 'A':A}))
        mcmc.run(rng_key, y=wave, mu=mu, init_params=initp)
        stime[i - a0] = np.mean(np.array(mcmc.get_samples()['t0']))
        print(stime[i - a0] - start[i]['T0'])
    return stime

def time_stan(a0, a1):
    stime = np.empty(a1 - a0)
    tlist = np.arange(window)
    t_auto = tlist[:, None] - tlist
    AV = p[2] * np.exp(-1 / 2 * np.power((np.log((t_auto + np.abs(t_auto)) * (1 / p[0] / 2)) * (1 / p[1])), 2))
    for i in range(a0, a1):
        wave = ent[i]['Waveform']
        mu = np.sum(wave) / gmu
        fit = stanmodel.sampling(data=dict(N=window, Tau=Tau, Sigma=Sigma, mu=mu, s=std / gsigma, sigma=gsigma / gmu, std=std, AV=AV, w=wave), warmup=500, iter=1500, seed=0)
        # print(pystan.check_hmc_diagnostics(fit))
        # print(fit.to_dataframe())
        stime[i - a0] = np.mean(fit['t0'])
    return stime

def time_pymc(a0, a1):
    stime = np.empty(a1 - a0)
    window = 60
    tlist = np.arange(window)
    t_auto = tlist[:, None] - tlist
    AV = p[2] * np.exp(-1 / 2 * np.power((np.log((t_auto + np.abs(t_auto)) * (1 / p[0] / 2)) * (1 / p[1])), 2))
    one = np.array([0., 1.])
    sigma = np.array([std / gsigma, gsigma / gmu])
    def model(y, mu):
        with pymc3.Model() as mix01:
            t0 = pymc3.Uniform('t0', lower=0., upper=float(window))
            if Tau == 0:
                pl = 1 / (Sigma * np.sqrt(2 * np.pi)) * np.exp(-(tlist - t0) ** 2 / (2 * Sigma**2)) * mu
            else:
                pl = Co * (1. - pymc3.math.erf((Alpha * Sigma ** 2 - (tlist - t0)) / (np.sqrt(2.) * Sigma))) * np.exp(-Alpha * (tlist - t0)) * mu + 1e-6
            pl = pymc3.math.stack([(1 - pl), pl], axis=1)
            Ai = [pymc3.NormalMixture('A_{:04d}'.format(i), w=pl[i], mu=one, sigma=sigma) for i in range(window)]
            A = pymc3.Deterministic('A', pymc3.math.stack(Ai))
            obs = pymc3.Normal('obs', mu=0., sigma=std, observed=y-pymc3.math.dot(AV, A))
        return mix01
    for i in range(a0, a1):
        wave = ent[i]['Waveform'][330:330+window]
        mu = np.sum(wave) / gmu
        with model(wave, mu):
            trace = pymc3.sample(1000, tune=1000, return_inferencedata=False)
            t = trace['t0']
            arviz.summary(trace, kind='stats')
        stime[i - a0] = np.mean(t)
    return stime

if args.Ncpu == 1:
    slices = [[0, N]]
else:
    chunk = N // args.Ncpu + 1
    slices = np.vstack((np.arange(0, N, chunk), np.append(np.arange(chunk, N, chunk), N))).T.astype(np.int).tolist()
if not os.path.exists('stanmodel.pkl'):
    os.system('python3 stanmodel.py')
stanmodel = pickle.load(open('stanmodel.pkl', 'rb'))

print('Initialization finished, real time {0:.4f}s, cpu time {1:.4f}s'.format(time.time() - global_start, time.process_time() - cpu_global_start))
tic = time.time()
cpu_tic = time.process_time()

ent = np.sort(ent, kind='stable', order=['TriggerNo', 'ChannelID'])
Chnum = len(np.unique(ent['ChannelID']))
e_pel = ent['TriggerNo'] * Chnum + ent['ChannelID']
e_pel, i_pel = np.unique(e_pel, return_index=True)
i_pel = np.append(i_pel, len(ent))

sdtp = np.dtype([('TriggerNo', np.uint32), ('ChannelID', np.uint32), ('tsfirsttruth', np.float64), ('tsfirstcharge', np.float64), ('tstruth', np.float64), ('tscharge', np.float64)])
ts = np.zeros(N, dtype=sdtp)
ts['TriggerNo'] = np.unique(ent['TriggerNo'])
ts['ChannelID'] = np.unique(ent['ChannelID'])
ts['tscharge'] = np.full(N, np.nan)
ts['tsfirsttruth'] = np.full(N, np.nan)
ts['tsfirstcharge'] = np.full(N, np.nan)

chunk = N // args.Ncpu + 1
slices = np.vstack((np.arange(0, N, chunk), np.append(np.arange(chunk, N, chunk), N))).T.astype(np.int).tolist()
# time_pyro(4, 10)
time_numpyro(0, 10)
# time_stan(4, 10)
# time_pymc(2, 4)
with Pool(min(args.Ncpu, cpu_count())) as pool:
    result = pool.starmap(partial(time_pyro), slices)

ts = np.hstack(result)
ts = np.sort(ts, kind='stable', order=['TriggerNo', 'ChannelID'])
print('Prediction generated, real time {0:.4f}s, cpu time {1:.4f}s'.format(time.time() - tic, time.process_time() - cpu_tic))

with h5py.File(args.opt, 'w') as opt:
    dset = opt.create_dataset('risetime', data=ts, compression='gzip')
    dset.attrs['Method'] = method
    dset.attrs['mu'] = Mu
    dset.attrs['tau'] = Tau
    dset.attrs['sigma'] = Sigma
    print('The output file path is {}'.format(args.opt))

print('Finished! Consuming {0:.2f}s in total, cpu time {1:.2f}s.'.format(time.time() - global_start, time.process_time() - cpu_global_start))