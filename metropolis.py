import time
import argparse

import h5py
import numpy as np
# np.seterr(all='raise')
from scipy.stats import poisson

import wf_func as wff

global_start = time.time()
cpu_global_start = time.process_time()

psr = argparse.ArgumentParser()
psr.add_argument('-o', dest='opt', type=str, help='output file')
psr.add_argument('ipt', type=str, help='input file')
psr.add_argument('--ref', type=str, help='reference file')
args = psr.parse_args()

fipt = args.ipt
fopt = args.opt
reference = args.ref

spe_pre = wff.read_model(reference, 1)
with h5py.File(fipt, 'r', libver='latest', swmr=True) as ipt:
    ent = ipt['Readout/Waveform'][:]
    pelist = ipt['SimTriggerInfo/PEList'][:]
    t0_truth = ipt['SimTruth/T'][:]
    N = len(ent)
    print('{} waveforms will be computed'.format(N))
    window = len(ent[0]['Waveform'])
    assert window >= len(spe_pre[0]['spe']), 'Single PE too long which is {}'.format(len(spe_pre[0]['spe']))
    Mu = ipt['Readout/Waveform'].attrs['mu'].item()
    Tau = ipt['Readout/Waveform'].attrs['tau'].item()
    Sigma = ipt['Readout/Waveform'].attrs['sigma'].item()
    gmu = ipt['SimTriggerInfo/PEList'].attrs['gmu'].item()
    gsigma = ipt['SimTriggerInfo/PEList'].attrs['gsigma'].item()
    PEList = ipt['SimTriggerInfo/PEList'][:]

p = spe_pre[0]['parameters']
if Tau != 0:
    Alpha = 1 / Tau
    Co = (Alpha / 2. * np.exp(Alpha ** 2 * Sigma ** 2 / 2.)).item()
std = 1.
Thres = wff.Thres
mix0sigma = 1e-3
mu0 = np.arange(1, int(Mu + 5 * np.sqrt(Mu)))
n_t = np.arange(1, 20)

n = 1
b_t0 = [0., 600.]

print('Initialization finished, real time {0:.02f}s, cpu time {1:.02f}s'.format(time.time() - global_start, time.process_time() - cpu_global_start))
tic = time.time()
cpu_tic = time.process_time()

ent = np.sort(ent, kind='stable', order=['TriggerNo', 'ChannelID'])
Chnum = len(np.unique(ent['ChannelID']))

dt = [('TriggerNo', np.uint32), ('ChannelID', np.uint32), ('istar', np.uint16), ('flip', np.int8), ('delta_nu', np.float64)]
mu0_dt = [('TriggerNo', np.uint32), ('ChannelID', np.uint32), ('mu_t', np.float64)]
TRIALS = 10000

def grid(cx, p1, z, t, N, sig2s, mus, step, accept, A):
    '''
    step: +1 加一个 PE, -1 减一个 PE, +2 PE 右移, -2 PE 左移
    Δν: 迈出这一步 ν 的变化
    '''
    # model selection vector
    s = np.zeros(N)

    if s[t] == 0: # 下边界
        step = 1 # 不论是 -1 还是 +-2，都转换成 +1
        # Q(1->0) / Q(0->1) = 1 / 4
        # 从 0 开始只有一种跳跃可能到 1，因此需要惩罚
        accept += np.log(4)
    elif s[t] == 1 and step == -1:
        # 1 -> 0: 行动后从 0 脱出的几率大，需要鼓励
        accept -= np.log(4)

    if abs(step) == 2:
        if t == 0: # 左边界
            if step == -2: # 在最左边，不能有 -2 向左移动
                step = 2
            if step == 2:
                # Q(移 1->0) / Q(移 0->1) = 1 / 2
                # 从 0 移动只能到 1，因此需要惩罚
                accept += np.log(2)
        elif t == 1 and step == -2:
            accept -= np.log(2)

        if t == N-1: # 右边界
            if step == 2: # 在最右边，不能有 2 向右移动
                step = -2
            if step == -2:
                # 从 N-1 只能到 N-2，惩罚
                accept += np.log(2)
        elif t == N-2 and step == 2:
            accept -= np.log(2)

        t_next = t + 1 if step == 2 else t - 1
        # Q(移 t_next -> t) / Q(移 t -> t_next)
        # 若 p(t_next) 很大，则应鼓励
        accept -= np.log(cha[t_next] / cha[t])

    def move(cx, z, t, step):
        '''
        step
        ====
        1: 在 t 加一个 PE
        -1: 在 t 减一个 PE
        '''
        fsig2s = step * sig2s[t]
        # Eq. (30) sig2s = 1 sigma^2 - 0 sigma^2
        beta_under = (1 + fsig2s * np.dot(A[:, t], cx[:, t]))
        beta = fsig2s / beta_under

        # Eq. (31) # sign of mus[t] and sig2s[t] cancels
        Δν = 0.5 * (beta * (z @ cx[:, t] + mus[t] / sig2s[t]) ** 2 - mus[t] ** 2 / fsig2s)
        # sign of space factor in Eq. (31) is reversed.  Because Eq. (82) is in the denominator.
        Δν -= 0.5 * np.log(beta_under) # space
        # poisson
        Δν += step * np.log(p1[t])
        if step == 1:
            Δν -= np.log(s[t] + 1)
        else: # step == -1
            Δν += np.log(s[t])

        # accept, prepare for the next
        # Eq. (33) istar is now n_pre.  It crosses n_pre and n, thus is in vector form.
        Δcx = -np.einsum('n,m,mp->np', beta * cx[:, t], cx[:, t], A, optimize=True)

        # Eq. (34)
        Δz = -step * A[:, t] * mus[t]
        return Δν, Δcx, Δz

    if abs(step) == 2:
        Δν0, Δcx0, Δz0 = move(cx, z, t, -1)
        Δν1, Δcx1, Δz1 = move(cx + Δcx0, z + Δz0, t_next, 1)
        Δν = Δν0 + Δν1
        Δcx = Δcx0 + Δcx1
        Δz = Δz0 + Δz1
    elif abs(step) == 1:
        Δν, Δcx, Δz = move(cx, z, t, step)

    if Δν >= accept:
        cx += Δcx
        z += Δz

        if abs(step) == 2:
            s[t] -= 1
            s[t_next] += 1
        elif abs(step) == 1:
            s[t] += step # update state
    else:
        # reject proposal
        step = 0
        Δν = 0

    return step, Δν

def metropolis(ent, sample, mu0, d_tlist):
    i_tlist = 0
    for ie, e in enumerate(ent):
        time_fbmp_start = time.time()
        eid = e["TriggerNo"]
        cid = e['ChannelID']
        assert cid == 0
        PEs = PEList[np.logical_and(PEList["TriggerNo"] == eid, PEList["PMTId"] == cid)]
        NPE_t = len(PEs)

        wave = e['Waveform'].astype(np.float64) * spe_pre[cid]['epulse']

        # initialization
        A, y, tlist, t0_t, t0_delta, cha, left_wave, right_wave = wff.initial_params(wave, spe_pre[e['ChannelID']], Tau, Sigma, gmu, Thres['lucyddm'], p, is_t0=False, is_delta=False, n=n)
        s_cha = np.cumsum(cha)
        # moving average filter of size 2*n+1
        cha = np.pad(s_cha[2*n+1:], (n+1, n), 'edge') - np.pad(s_cha[:-(2*n+1)], (n+1, n), 'edge')
        cha += 1e-8 # for completeness of the random walk.
        o_tlist = i_tlist + len(tlist)
        d_tlist[i_tlist:o_tlist] = list(zip(np.repeat(eid, o_tlist - i_tlist),
                                            np.repeat(cid, o_tlist - i_tlist),
                                            tlist, cha))
        i_tlist = o_tlist
        t0_t = t0_truth['T0'][ie] # override with truth to debug mu
        mu_t = abs(y.sum() / gmu)
        mu0[ie] = (eid, cid, mu_t)
        # Eq. (9) where the columns of A are taken to be unit-norm.
        mus = np.sqrt(np.diag(np.matmul(A.T, A)))
        A = A / mus

        '''
        A: basis dictionary
        p1: prior probability for each bin.
        sig2w: variance of white noise.
        sig2s: variance of signal x_i.
        mus: mean of signal x_i.
        TRIALS: number of Metropolis steps.
        '''

        p1 = mu_t * wff.convolve_exp_norm(tlist - t0_t, Tau, Sigma) / n

        sig2w = spe_pre[cid]['std'] ** 2
        sig2s = (gsigma * mus / gmu) ** 2

        # Only for multi-gaussian with arithmetic sequence of mu and sigma
        # N: number of t bins
        # M: length of the waveform clip
        M, N = A.shape

        # nu: nu for all s_n=0.
        ν = -0.5 * np.linalg.norm(y) ** 2 / sig2w - 0.5 * M * np.log(2 * np.pi)
        ν -= 0.5 * M * np.log(sig2w)
        ν += poisson.logpmf(0, p1).sum()

        # Eq. (29)
        cx = A / sig2w
        # mu = 0 => (y - A * mu -> z)
        z = y

        # Metropolis on a grid
        istar = np.random.choice(range(N), TRIALS, p=cha/np.sum(cha))
        # -1 PE, +1 PE, 左移 PE, 右移 PE
        flip = np.random.choice((-1, 1, -2, 2), TRIALS)
        Δν_history = np.zeros(TRIALS) # list of Δν's
        for i, accept in enumerate(np.log(np.random.uniform(size=TRIALS))):
            step, Δν = grid(cx, p1, z, istar[i], N, sig2s, mus, flip[i], accept, A)
            Δν_history[i] = Δν
            flip[i] = step

        sample[ie*TRIALS:(ie+1)*TRIALS] = list(zip(np.repeat(eid, TRIALS), 
                                                   np.repeat(cid, TRIALS), 
                                                   istar, flip, Δν_history))
    d_tlist.resize((o_tlist,))

with h5py.File(fopt, 'w') as opt:
    sample = opt.create_dataset('sample', shape=(N*TRIALS,), dtype=dt)
    mu0 = opt.create_dataset('mu0', shape=(N,), dtype=mu0_dt)
    d_tlist = opt.create_dataset('tlist', shape=(N*1024,), 
                                 dtype=[('TriggerNo', np.uint32), ('ChannelID', np.uint32), 
                                        ('t_s', np.float16), ('q_s', np.float32)], chunks=True)
    metropolis(ent, sample, mu0, d_tlist)
    print('The output file path is {}'.format(fopt))

print('Prediction generated, real time {0:.02f}s, cpu time {1:.02f}s'.format(time.time() - tic, time.process_time() - cpu_tic))

print('Finished! Consuming {0:.02f}s in total, cpu time {1:.02f}s.'.format(time.time() - global_start, time.process_time() - cpu_global_start))
