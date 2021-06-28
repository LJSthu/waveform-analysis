import numpy as np
import numpyro
import wf_func as wff
from numba import jit
from scipy import optimize, special
from scipy.stats import poisson
import math
import os, h5py
templateProbability = np.array([68.74,16.58,8.595,6.022])
normalTplProbability = templateProbability/np.sum(templateProbability)
defaultHnumax = 200
defaultpetimes = 4
# calculate the probability matrxi
def hnu2PEProbability(probability,hnumax=200,petimes=4):
    # probability is the mcp charge response fit result, the first row and first column is for zero hnu and PE
    E = np.zeros((hnumax+1, hnumax*petimes+1))
    E[0,0] = 1
    E[1,1:(petimes+1)] = probability
    # hnumax+1 is the hnumax hnu
    for i in range(2,hnumax+1):
        for j in range(i,5):
            tmpE = np.zeros(4)
            tmpE[:j] = E[(i-1),(j-1)::-1]
            E[i,j] = np.sum(tmpE*probability)
        for j in range(5, 4*i+1):
            tmpE = E[(i-1),(j-1):(j-5):-1]
            E[i,j] = np.sum(tmpE*probability)
    return E
def hnu2PEProbabilityLog(probability,hnumax=200,petimes=4):
    logprobability = np.log(probability)
    E = np.zeros((hnumax+1, hnumax*petimes+1))
    E[0,0] = 1
    E[1,1:(petimes+1)] = np.log(probability)
    for i in range(2,hnumax+1):
        # because the length is not enough when i< i+3
        for j in range(i,i+3):
            tmpE = E[(i-1),(j-1):(i-2):-1]
            E[i,j] = special.logsumexp(tmpE+logprobability[:(j-i+1)])
        for j in range(i+3, 4*(i-1)+2):
            tmpE = E[(i-1),(j-1):(j-5):-1]
            E[i,j] = special.logsumexp(tmpE+logprobability)
        for j in range(4*(i-1)+2,4*i+1):
            tmpE = E[(i-1),(4*(i-1)):(j-5):-1]
            E[i,j] = special.logsumexp(tmpE+logprobability[-(4*i-j+1):])
    return E
def storehnu(outfile='mcpEin.h5'):
    with h5py.File(outfile, 'w') as opt:
        opt.create_dataset('hnu',data=hnu2PEProbability(normalTplProbability),compression='gzip')
        opt.create_dataset('hnu_log', data=hnu2PEProbabilityLog(normalTplProbability),compression='gzip')
#hnu2PEmatrix = hnu2PEProbability(normalTplProbability)
#hnu2PEmatrixLog = hnu2PEProbabilityLog(normalTplProbability)
def readhnu(infile='mcpEin.h5'):
    if not os.path.exists(infile):
        storehnu(infile)
    with h5py.File(infile, 'r') as ipt:
        hnu2PEmatrix = hnu2PEProbability(normalTplProbability)
        hnu2PEmatrixLog = hnu2PEProbabilityLog(normalTplProbability)
    return hnu2PEmatrix, hnu2PEmatrixLog
hnu2PEmatrix, hnu2PEmatrixLog = readhnu()
def lightCurve(t0, mu, binsT, tau, sigma, binwidth=0.1):
    # use the ligth curve distribution from wff
    expectM = mu * wff.convolve_exp_norm(binsT-t0, tau, sigma)*binwidth
    return expectM
def hypo0(expectM):
    return np.exp(-expectM)

def hypo1(expecthnu, hnu2PEp):
    return np.dot(expecthnu, hnu2PEp)
@jit(nopython=True)
def nfactoriallog(a,n):
    a[0] = 0
    for i in range(1,n):
        a[i] = a[i-1]+np.log(i)
    return a
@jit(nopython=True)
def logsumexpb(values, index=None, b=None):
    """Stole from scipy.special.logsumexp

    Parameters
    ----------
    values : array_like Input array.

    Returns
    -------
    res : ndarray
        The result, ``np.log(np.sum(np.exp(a)))`` calculated in a numerically
        more stable way. If `b` is given then ``np.log(np.sum(b*np.exp(a)))``
        is returned.
    """
    a_max = np.max(values)
    tmp = np.exp(values - a_max)
    for i in range(values.shape[0]):
        tmp[i] = tmp[i] * b[i] 
    s = np.sum(tmp)
    return np.log(s) + a_max

def hypo(expectM, cstar, indexstar):
    binsp = np.tile(hypo0(expectM), (cstar.shape[0],1))
    for i in range(cstar.shape[0]):
        for j in range(len(indexstar[i])):
            # indexstar[i][j]  is the index of nonzeros
            expecthnu = poisson.pmf(np.arange(defaultHnumax+1), expectM[indexstar[i][j]])
            assert(cstar[i,indexstar[i][j]]>=1)
            binsp[i, indexstar[i][j]] = hypo1(expecthnu, hnu2PEmatrix[:,cstar[i,indexstar[i][j]]])
    return binsp
def hypolog(expectM, cstar, indexstar):
    binsp = np.tile(-expectM, (cstar.shape[0],1))
    nflog = nfactoriallog(np.arange(defaultHnumax+1), defaultHnumax+1)
    for i in range(cstar.shape[0]):
        for j in range(len(indexstar[i])):
            expecthnu = np.log(expectM[indexstar[i][j]])*np.arange(defaultHnumax+1)- expectM[indexstar[i][j]]-nflog
            binsp[i, indexstar[i][j]] = logsumexpb(expecthnu, b=hnu2PEmatrix[:,cstar[i,indexstar[i][j]]])
    return binsp
def likelihood(x,*args):
    binsT, tau, sigma,c_star, p_star, index_star, mu,binwidth = args
    lightC = lightCurve(x[0],mu,binsT,tau,sigma,binwidth)
    prob = hypo(lightC, c_star, index_star)
    L = -special.logsumexp(np.sum(np.log(prob),axis=1),b=p_star)
    #L = -np.dot(np.sum(np.log(prob),axis=1),p_star)
    return L
def likelihoodlog(x,*args):
    binsT, tau, sigma,c_star, logp_star, index_star, binwidth = args
    lightC = lightCurve(x[0],x[1],binsT,tau,sigma, binwidth)
    #prob = hypo(lightC, c_star, index_star)
    prob = hypolog(lightC, c_star, index_star)
    L = -special.logsumexp(np.sum(prob,axis=1)+logp_star)
    return L
def findNonzero(cstar):
    indexstar = [[]]*cstar.shape[0]
    for i in range(cstar.shape[0]):
        indexstar[i] = np.where(cstar[i]>0)[0]
    return indexstar
def optimizet0mu(binsT, tau, sigma,c_star, p_star, t0guess,method='SLSQP'):
    index_star = findNonzero(c_star)
    expectnum = np.sum(c_star)/len(c_star)
    fitresults = []
    for delta in np.arange(0,100,0.2):
        for n in range(1,int(expectnum)+2):
            x0 = [t0guess-delta]
            fitresults.append((optimize.minimize(likelihood, x0, method=method,bounds=((t0guess-200, t0guess+50)),args=(binsT, tau, sigma,c_star, p_star, index_star,n)),n))#,options={'eps':0.01}))
    return min(fitresults,key=lambda x:x[0].fun)
def optimizeBotht0mulog(binsT, tau, sigma,c_star, logp_star, t0guess,method='SLSQP'):
    # minimize t0 and mu both
    index_star = findNonzero(c_star)
    expectnum = np.sum(c_star)/len(c_star)
    binwidth = binsT[1]-binsT[0]
    fitresults = []
    for delta in np.arange(-10,90,10):
        for n in range(np.max([1, int(expectnum)-10]),int(expectnum)+2):
            x0 = [t0guess-delta, n]
            fitresults.append(optimize.minimize(likelihoodlog, x0, method=method,bounds=((t0guess-200, t0guess+100),(0,500)),args=(binsT, tau, sigma,c_star, logp_star, index_star,binwidth)))#,options={'eps':0.01}))
    return min(fitresults,key=lambda x:x.fun)
def optimizeBotht0mulogFromBest(binsT, tau, sigma,c_star, logp_star, t0guess,muguess,method='SLSQP'):
    # minimize t0 and mu both
    index_star = findNonzero(c_star)
    expectnum = np.sum(c_star)/len(c_star)
    fitresults = []
    for delta in np.arange(-10,10,1):
        for n in np.arange(1,muguess+2):
            x0 = [t0guess-delta, n]
            fitresults.append(optimize.minimize(likelihoodlog, x0, method=method,bounds=((t0guess-200, t0guess+50),(0,500)),args=(binsT, tau, sigma,c_star, logp_star, index_star)))#,options={'eps':0.01}))
    return min(fitresults,key=lambda x:x.fun)
def hypologBS(expectM, cstar, indexstar):
    binsp = np.tile(-expectM, (cstar.shape[0],1))
    nflog = nfactoriallog(np.arange(defaultHnumax+1), defaultHnumax+1)
    for i in range(cstar.shape[0]):
        # indexstar[i][j]  is the index of nonzeros
        binsp[i, indexstar[i]] += np.log(expectM[indexstar[i]])*cstar[i][indexstar[i]] - nflog[cstar[i][indexstar[i]]]
    return binsp
def likelihoodlogBS(x,*args):
    binsT, tau, sigma,c_star, logp_star, index_star, binwidth = args
    lightC = lightCurve(x[0],x[1],binsT,tau,sigma, binwidth)
    prob = hypologBS(lightC, c_star, index_star)
    L = -special.logsumexp(np.sum(prob, axis=1) + logp_star)
    return L
def optimizeBotht0mulogBS(binsT, tau, sigma,c_star, logp_star, t0guess,method='SLSQP'):
    # minimize t0 and mu both
    index_star = findNonzero(c_star)
    expectnum = np.sum(c_star)/len(c_star)
    binwidth = binsT[1]-binsT[0]
    fitresults = []
    for delta in np.arange(-10,90,10):
        for n in range(np.max([1, int(expectnum)-10]),int(expectnum)+2):
            x0 = [t0guess-delta, n]
            fitresults.append(optimize.minimize(likelihoodlogBS, x0, method=method,bounds=((t0guess-200, t0guess+100),(0,500)),args=(binsT, tau, sigma,c_star, logp_star, index_star,binwidth)))#,options={'eps':0.01}))
    return min(fitresults,key=lambda x:x.fun)
def fbmpr_custom_deactive(y, A, p1, sig2w, sig2s, mus, D, einsM, stop=0, pmax=50, truth=None, i=None, left=None, right=None, tlist=None, gmu=None, para=None):
    '''
    this method is for multi-gaussian, each bin obey Poisson distribution mixed with Gaussian.
    p1: prior probability for each bin.
    sig2w: variance of white noise.
    sig2s: variance of signal x_i.
    mus: mean of signal x_i.
    '''
    # Only for multi-gaussian with arithmetic sequence of mu and sigma
    M, N = A.shape

    p = 1 - poisson.pmf(0, p1).mean()
    # Eq. (25)
    nu_true_mean = -M / 2 - M / 2 * np.log(sig2w) - p * N / 2 * np.log(sig2s / sig2w + 1) - M / 2 * np.log(2 * np.pi) + N * np.log(1 - p) + p * N * np.log(p / (1 - p))
    nu_true_stdv = np.sqrt(M / 2 + N * p * (1 - p) * (np.log(p / (1 - p)) - np.log(sig2s / sig2w + 1) / 2) ** 2)
    nu_stop = nu_true_mean + stop * 3*nu_true_stdv

    Q = 10
    lnn = np.concatenate([[0],np.log(np.arange(1,np.max([Q+1,einsM.shape[0]])))])
    lnncum = np.cumsum(lnn)
    hnulogp = -p1+np.log(p1)*np.arange(0,einsM.shape[0]).reshape(1,-1)-lnncum[:einsM.shape[0]].reshape(1,-1)
    pelogp = special.logsumexp(hnulogp.reshape(hnulogp.shape[0],hnulogp.shape[1],1)+einsM[:,:(Q+1)], axis=1)

    psy_thresh = 1e-4
    # upper limit of number of PEs.
    P = np.max([math.ceil(min(M, p1.sum() + 3 * np.sqrt(p1.sum()))), pmax])
    # depth of the search
    D = min(len(p1), D)
    D = 3
    T = np.full((P, D), 0,dtype='i,i')
    nu = np.full((P, D), -np.inf)
    xmmse = np.zeros((P, D, N),dtype='i')
    expectx = np.zeros((P,D,N))
    cc = np.zeros((P, D, N))
    d_tot = D

    # nu_root: nu for all s_n=0.
    nu_root = -0.5 * np.linalg.norm(y) ** 2 / sig2w - 0.5 * M * np.log(2 * np.pi) - 0.5 * M * np.log(sig2w) + np.log(poisson.pmf(0, p1)).sum()
    #print(nu_root, nusy(y,A,xmmse[0,0],sig2w,sig2s,mus,p1))
    # Eq. (29)
    cx_root = A / sig2w
    # Eq. (31)
    betaxts_root = np.zeros((N,Q+1))
    nuxt_root = np.zeros((N,Q+1))
    nuxt_root[:,0] = nu_root
    for i in range(Q):
        # Eq. (30) sig2s = 1 sigma^2 - 0 sigma^2
        betaxts_root[:,i+1] = (i+1)*sig2s / (1 + (i+1)*sig2s * np.einsum('ij,ij->j', A, cx_root))
        betaxt_root = betaxts_root[:,i+1]
        nuxt_root[:,i+1] = nu_root + 0.5 * (betaxt_root * (y @ cx_root + mus / sig2s) ** 2  - (i+1)*mus ** 2 / sig2s + np.log(betaxt_root/(i+1)/ sig2s)) + pelogp[:,(i+1)]-pelogp[:,0]# np.log(poisson.pmf(i+1, p1) / poisson.pmf(0, p1))
        # for j in range(N):
        #     tmp = np.zeros((N),dtype='i')
        #     tmp[j] = i+1
            #print('{},{}:{},{}'.format(i,j,nuxt_root[j,i+1], nusy(y,A,tmp,sig2w,sig2s,mus,p1)))
    pan_root = np.zeros(N)

    # Repeated Greedy Search
    for d in range(D):
        nuxt = nuxt_root.copy()
        z = y.copy()
        cx = cx_root.copy()
        betaxts = betaxts_root.copy()
        pan = pan_root.copy()
        nutemp=0
        for p in range(P):
            # look for duplicates of nu and nuxt, set to -inf.
            # only inspect the same number of PEs in Row p.
            if abs(np.max(nuxt)-nutemp)<1e-2:
                break
            nuxtshadow = np.where(np.sum(np.abs(nuxt - nu[:, :(d+1),np.newaxis,np.newaxis]) < 1e-4, axis=(0,1)), -np.inf, nuxt)
            nustar = np.max(nuxtshadow)
            nutemp = nustar
            #print(nustar)
            assert(~np.isnan(nustar))
            istar = np.argmax(nuxtshadow)
            nu[p, d] = nustar
            T[p, d] = (istar//(1+Q), istar%(1+Q))
            pan[T[p,d][0]] = T[p,d][1]
            istar = T[p,d][0]
            # Eq. (33)
            betaxt = betaxts[istar]
            #cx = cxs[T[p,d][1]-1,:,:]
            #cxs = cx.reshape(1,cx.shape[0],cx.shape[1]) - np.einsum('qn,y,yp->qnp', betaxt.reshape(-1,1) * cx[:, istar], cx[:, istar], A)
            cx = cx - np.einsum('n,m,mp->np', betaxt[T[p,d][1]] * cx[:, istar], cx[:, istar], A)
            # Eq. (34)
            #z = zs[T[p,d][1]-1,:]
            if p==0:
                z = z - A[:, istar] * mus * (T[p,d][1])
            else:
                z = z - A[:, istar] * mus * (T[p,d][1]-xmmse[p-1,d,T[p,d][0]])
            for i in range(p+1):
                xmmse[p, d, T[i,d][0]] = T[i,d][1]
            expectx[p,d] = xmmse[p,d]*mus + sig2s*xmmse[p,d]*np.dot(z,cx)
            #print(xmmse[p,d])
            #print(nustar, nusy(y,A,xmmse[p,d],sig2w,sig2s,mus,p1))
            for i in range(Q+1):
                # Eq. (30)
                selectindex = (i)!=xmmse[p,d,:]
                #betaxts[:,i] = (i+1-xmmse[p,d,:])*sig2s / (1 + (i+1-xmmse[p,d,:])*sig2s * np.sum(A * cxs[i,:,:], axis=0))
                betaxts[:,i] = (i-xmmse[p,d,:])*sig2s / (1 + (i-xmmse[p,d,:])*sig2s * np.sum(A * cx, axis=0))
                betaxt = betaxts[:,i]
                # Eq. (31)
                #nuxt[selectindex,i] = (nustar + 0.5 * (betaxt * (z @ cx + mus / sig2s) ** 2 - 0.5*(i+1-xmmse[p,d,:])*mus ** 2 / sig2s + 0.5*np.log(betaxt/(i+1-xmmse[p,d,:]) / sig2s)) + np.log(poisson.pmf((i+1), mu=p1) / poisson.pmf(xmmse[p,d,:], mu=p1)))[selectindex]
                #nuxt[selectindex,i] = (nustar + 0.5 * (betaxt * (z @ cxs[i,:,:] + mus / sig2s) ** 2 - 0.5*(i+1-xmmse[p,d,:])*mus ** 2 / sig2s + 0.5*np.log(betaxt/(i+1-xmmse[p,d,:]) / sig2s)) + (i+1-xmmse[p,d,:])*np.log(p1)-(lnncum[i]-lnncumL))[selectindex]
                nuxt[selectindex,i] = (nustar + 0.5 * (betaxt * (z @ cx + mus / sig2s) ** 2 - (i-xmmse[p,d,:])*mus ** 2 / sig2s + np.log(betaxt/(i-xmmse[p,d,:]) / sig2s)) + pelogp[:,i]-pelogp[:,xmmse[p,d,:]])[selectindex]
                nanindex = np.where(np.isnan(nuxt[:,i]))
                nuxt[nanindex,i] = -np.inf
            # nuxt[t] = -np.inf
        #print(p)
        if max(nu[:, d]) > nu_stop:
            d_tot = d + 1
            break
        #print(d)
    nu_bk = nu[:, :d_tot]
    nu = nu[:, :d_tot].T.flatten()

    indx = np.argsort(nu)[::-1]
    d_max = math.floor(indx[0] // P) + 1
    num = min(min(int(np.sum(nu > nu.max() + np.log(psy_thresh))), d_tot * P), 20)
    nu_star = nu[indx[:num]]
    psy_star = np.exp(nu_star - nu.max()) / np.sum(np.exp(nu_star - nu.max()))

    T_star = [sorted(T[:(indx[k] % P) + 1, indx[k] // P],key=lambda t: t[0]) for k in range(num)]
    xmmse_star = np.empty((num, N),dtype='i')
    expectx_star = np.empty((num, N))
    for k in range(num):
        xmmse_star[k] = xmmse[indx[k] % P, indx[k] // P]
        expectx_star[k] = expectx[indx[k] % P, indx[k] // P]
    #print(nu_star)
    xmmse = np.average(xmmse_star, weights=psy_star, axis=0)
    expectx_mean = np.average(expectx_star, weights=psy_star, axis=0)
    return xmmse, xmmse_star, psy_star, nu_star, T_star, d_tot, d_max,expectx_mean, expectx_star

# define the process from number of photon to pe
def photon2pe(nphoton, pmf=normalTplProbability):
    return np.random.choice(np.arange(1,templateProbability.shape[0]+1),size=nphoton, p=pmf)
#class mcpModel(numpyro.distributions.distribution.Distribution):

def mcpModel(pes, pmf=normalTplProbability,logits=range(1,len(normalTplProbability)+1)):
    # pe expect value
    p0 = numpyro.sample('p0', numpyro.distributions.Uniform(0,10))
    # pe poisson value
    p1 = numpyro.sample('p1', numpyro.distributions.Poisson(p0))
    obs = 0
    for i in range(p1):
        obs += numpyro.sample('obs', numpyro.distributions.Categorical(pmf, logits))
    return obs
def mcpAllocateCharge(ps, charges):
    pcs = np.zeros(ps.shape)
    begin = 0
    for i in range(len(ps)):
        pcs[i] = np.sum(charges[begin:(begin+ps[i])])
    return pcs
def mcpMC(pes):
    nuts_kernel = numpyro.infer.NUTS(mcpModel, init_strategy=numpyro.infer.initialization.init_to_value(values={'p0': jnp.array([0.5])}))
    mcmc = numpyro.infer.MCMC(nuts_kernel, num_samples=100,num_warmup=30,progress_bar=False)
    mcmc.run(rng_key,pes=pes)
    p0 = np.array(mcmc.get_samples()['p0'])
    p0 = np.array(mcmc.get_samples()['p1'])
def fbmpr_poisson_reduced(y, A, p1, sig2w, sig2s, mus, D, stop=0, truth=None, i=None, left=None, right=None, tlist=None, gmu=None, para=None):
    '''
    this method is for multi-gaussian, each bin obey Poisson distribution mixed with Gaussian.
    p1: prior probability for each bin.
    sig2w: variance of white noise.
    sig2s: variance of signal x_i.
    mus: mean of signal x_i.
    '''
    # Only for multi-gaussian with arithmetic sequence of mu and sigma
    M, N = A.shape

    p = 1 - poisson.pmf(0, p1).mean()
    # Eq. (25)
    nu_true_mean = -M / 2 - M / 2 * np.log(sig2w) - p * N / 2 * np.log(sig2s / sig2w + 1) - M / 2 * np.log(2 * np.pi) + N * np.log(1 - p) + p * N * np.log(p / (1 - p))
    nu_true_stdv = np.sqrt(M / 2 + N * p * (1 - p) * (np.log(p / (1 - p)) - np.log(sig2s / sig2w + 1) / 2) ** 2)
    nu_stop = nu_true_mean + stop * nu_true_stdv

    psy_thresh = 1e-4
    # upper limit of number of PEs.
    P = math.ceil(min(M, p1.sum() + 3 * np.sqrt(p1.sum())))
    # depth of the search
    D = min(len(p1), D)
    D = 2
    T = np.full((P, D), 0,dtype='i,i')
    nu = np.full((P, D), -np.inf)
    xmmse = np.zeros((P, D, N),dtype='i')
    cc = np.zeros((P, D, N))
    d_tot = D

    # nu_root: nu for all s_n=0.
    nu_root = -0.5 * np.linalg.norm(y) ** 2 / sig2w - 0.5 * M * np.log(2 * np.pi) - 0.5 * M * np.log(sig2w) + np.log(poisson.pmf(0, p1)).sum()
    # Eq. (29)
    cx_root = A / sig2w
    # Eq. (31)
    Q = 30
    nuxt_root = np.zeros((N,Q))
    lnn = np.log(np.arange(1,Q+1))
    lnncum = np.cumsum(lnn)
    betaxts_root = np.zeros((N,Q))
    for i in range(Q):
        # Eq. (30) sig2s = 1 sigma^2 - 0 sigma^2
        betaxts_root[:,i] = (i+1)*sig2s / (1 + (i+1)*sig2s * np.einsum('ij,ij->j', A, cx_root))
        betaxt_root = betaxts_root[:,i]
        nuxt_root[:,i] = nu_root + 0.5 * (betaxt_root * (y @ cx_root + mus / sig2s) ** 2  - 0.5*(i+1)*mus ** 2 / sig2s + 0.5*np.log(betaxt_root/(i+1)/ sig2s)) + (i+1)*np.log(p1)-lnncum[i]# np.log(poisson.pmf(i+1, p1) / poisson.pmf(0, p1))
    pan_root = np.zeros(N)

    # Repeated Greedy Search
    for d in range(D):
        nuxt = nuxt_root.copy()
        z = y.copy()
        zs = np.tile(z,(Q,1))
        cx = cx_root.copy()
        cxs = np.tile(cx,(Q,1,1))
        betaxts = betaxts_root.copy()
        pan = pan_root.copy()
        for p in range(P):
            # look for duplicates of nu and nuxt, set to -inf.
            # only inspect the same number of PEs in Row p.
            nuxtshadow = np.where(np.sum(np.abs(nuxt - nu[:, :(d+1),np.newaxis,np.newaxis]) < 1e-4, axis=(0,1)), -np.inf, nuxt)
            nustar = np.max(nuxtshadow)
            #print(nustar)
            assert(~np.isnan(nustar))

            istar = np.argmax(nuxtshadow)
            nu[p, d] = nustar
            T[p, d] = (istar//Q, istar%Q)
            pan[T[p,d][0]] = T[p,d][1]+1
            istar = T[p,d][0]
            # Eq. (33)
            betaxt = betaxts[istar]
            #cx = cxs[T[p,d][1]-1,:,:]
            #cxs = cx.reshape(1,cx.shape[0],cx.shape[1]) - np.einsum('qn,y,yp->qnp', betaxt.reshape(-1,1) * cx[:, istar], cx[:, istar], A)
            cx = cx - np.einsum('n,m,mp->np', betaxt[T[p,d][1]] * cx[:, istar], cx[:, istar], A)
            # Eq. (34)
            #z = zs[T[p,d][1]-1,:]
            if p==0:
                z = z - A[:, istar] * mus * (T[p,d][1]+1)
            else:
                z = z - A[:, istar] * mus * (T[p,d][1]+1-xmmse[p-1,d,T[p,d][0]])
            for i in range(p):
                xmmse[p, d, T[i,d][0]] = T[i,d][1]+1
            for i in range(Q):
                # Eq. (30)
                selectindex = (i+1)!=xmmse[p,d,:]
                #betaxts[:,i] = (i+1-xmmse[p,d,:])*sig2s / (1 + (i+1-xmmse[p,d,:])*sig2s * np.sum(A * cxs[i,:,:], axis=0))
                betaxts[:,i] = (i+1-xmmse[p,d,:])*sig2s / (1 + (i+1-xmmse[p,d,:])*sig2s * np.sum(A * cx, axis=0))
                betaxt = betaxts[:,i]
                # Eq. (31)
                #nuxt[selectindex,i] = (nustar + 0.5 * (betaxt * (z @ cx + mus / sig2s) ** 2 - 0.5*(i+1-xmmse[p,d,:])*mus ** 2 / sig2s + 0.5*np.log(betaxt/(i+1-xmmse[p,d,:]) / sig2s)) + np.log(poisson.pmf((i+1), mu=p1) / poisson.pmf(xmmse[p,d,:], mu=p1)))[selectindex]
                lnncumL = lnncum[xmmse[p,d,:]-1]
                lnncumL[xmmse[p,d,:]==0] = 0
                #nuxt[selectindex,i] = (nustar + 0.5 * (betaxt * (z @ cxs[i,:,:] + mus / sig2s) ** 2 - 0.5*(i+1-xmmse[p,d,:])*mus ** 2 / sig2s + 0.5*np.log(betaxt/(i+1-xmmse[p,d,:]) / sig2s)) + (i+1-xmmse[p,d,:])*np.log(p1)-(lnncum[i]-lnncumL))[selectindex]
                nuxt[selectindex,i] = (nustar + 0.5 * (betaxt * (z @ cx + mus / sig2s) ** 2 - 0.5*(i+1-xmmse[p,d,:])*mus ** 2 / sig2s + 0.5*np.log(betaxt/(i+1-xmmse[p,d,:]) / sig2s)) + (i+1-xmmse[p,d,:])*np.log(p1)-(lnncum[i]-lnncumL))[selectindex]
                nanindex = np.where(np.isnan(nuxt[:,i]))
                nuxt[nanindex,i] = -np.inf
            # nuxt[t] = -np.inf

        if max(nu[:, d]) > nu_stop:
            d_tot = d + 1
            break
        #print(d)
    # revise = np.log(poisson.pmf(np.arange(1, P+1), p1.sum())) - special.logsumexp(np.log(poisson.pmf(cc[:, :d_tot], p1)).sum(axis=-1), axis=1)
    # revise = np.log(poisson.pmf(np.arange(1, P+1), p1.sum()))
    #revise = norm.logpdf(p1.sum() * mus, loc=np.arange(1, P+1) * mus, scale=np.sqrt(np.arange(1, P+1) * sig2s)) - np.log(poisson.pmf(np.arange(1, P+1), p1.sum()))
    #nu[:, :d_tot] = nu[:, :d_tot] + revise[:, None]
    # pp = poisson.pmf(np.arange(1, P+1), p1.sum())
    # nu[:, :d_tot][np.random.uniform(size=nu[:, :d_tot].shape) > pp[:, None] / pp.max()] = -np.inf
    nu_bk = nu[:, :d_tot]
    nu = nu[:, :d_tot].T.flatten()

    indx = np.argsort(nu)[::-1]
    d_max = math.floor(indx[0] // P) + 1
    num = min(min(int(np.sum(nu > nu.max() + np.log(psy_thresh))), d_tot * P), 20)
    nu_star = nu[indx[:num]]
    psy_star = np.exp(nu_star - nu.max()) / np.sum(np.exp(nu_star - nu.max()))

    T_star = [sorted(T[:(indx[k] % P) + 1, indx[k] // P],key=lambda t: t[0]) for k in range(num)]
    xmmse_star = np.empty((num, N),dtype='i')
    for k in range(num):
        xmmse_star[k] = xmmse[indx[k] % P, indx[k] // P]
    #print(nu_star)
    xmmse = np.average(xmmse_star, weights=psy_star, axis=0)

    return xmmse, xmmse_star, psy_star, nu_star, T_star, d_tot, d_max
def nusy(y,A,s,sigmaw2,sigmas2,mu,nus,Q=10):
    # nus expect nu for each bin
    # mu charge mu
    m,n = A.shape
    lnn = np.concatenate([[0],np.log(np.arange(1,Q+1))])
    lnncum = np.cumsum(lnn)
    residual = y - A.dot(s*mu)
    R = np.diag(s*sigmas2)
    phis = A@R@A.T+sigmaw2*np.eye(m)
    return -0.5*residual.T@np.linalg.inv(phis)@residual-0.5*np.log(np.linalg.det(phis))-0.5*m*np.log(2*np.pi)+np.sum(s*np.log(nus))-np.sum(nus)-np.sum(lnncum[s])
def fbmpr_poisson_deactive(y, A, p1, sig2w, sig2s, mus, D, stop=0, pmax=50, truth=None, i=None, left=None, right=None, tlist=None, gmu=None, para=None):
    '''
    this method is for multi-gaussian, each bin obey Poisson distribution mixed with Gaussian.
    p1: prior probability for each bin.
    sig2w: variance of white noise.
    sig2s: variance of signal x_i.
    mus: mean of signal x_i.
    '''
    # Only for multi-gaussian with arithmetic sequence of mu and sigma
    M, N = A.shape

    p = 1 - poisson.pmf(0, p1).mean()
    # Eq. (25)
    nu_true_mean = -M / 2 - M / 2 * np.log(sig2w) - p * N / 2 * np.log(sig2s / sig2w + 1) - M / 2 * np.log(2 * np.pi) + N * np.log(1 - p) + p * N * np.log(p / (1 - p))
    nu_true_stdv = np.sqrt(M / 2 + N * p * (1 - p) * (np.log(p / (1 - p)) - np.log(sig2s / sig2w + 1) / 2) ** 2)
    nu_stop = nu_true_mean + stop * 3*nu_true_stdv

    psy_thresh = 1e-4
    # upper limit of number of PEs.
    P = np.max([math.ceil(min(M, p1.sum() + 3 * np.sqrt(p1.sum()))), pmax])
    # depth of the search
    D = min(len(p1), D)
    D = 3
    T = np.full((P, D), 0,dtype='i,i')
    nu = np.full((P, D), -np.inf)
    xmmse = np.zeros((P, D, N),dtype='i')
    expectx = np.zeros((P,D,N))
    cc = np.zeros((P, D, N))
    d_tot = D

    # nu_root: nu for all s_n=0.
    nu_root = -0.5 * np.linalg.norm(y) ** 2 / sig2w - 0.5 * M * np.log(2 * np.pi) - 0.5 * M * np.log(sig2w) + np.log(poisson.pmf(0, p1)).sum()
    #print(nu_root, nusy(y,A,xmmse[0,0],sig2w,sig2s,mus,p1))
    # Eq. (29)
    cx_root = A / sig2w
    # Eq. (31)
    Q = 10
    nuxt_root = np.zeros((N,Q+1))
    lnn = np.concatenate([[0],np.log(np.arange(1,Q+1))])
    lnncum = np.cumsum(lnn)
    betaxts_root = np.zeros((N,Q+1))
    nuxt_root[:,0] = nu_root
    for i in range(Q):
        # Eq. (30) sig2s = 1 sigma^2 - 0 sigma^2
        betaxts_root[:,i+1] = (i+1)*sig2s / (1 + (i+1)*sig2s * np.einsum('ij,ij->j', A, cx_root))
        betaxt_root = betaxts_root[:,i+1]
        nuxt_root[:,i+1] = nu_root + 0.5 * (betaxt_root * (y @ cx_root + mus / sig2s) ** 2  - (i+1)*mus ** 2 / sig2s + np.log(betaxt_root/(i+1)/ sig2s)) + (i+1)*np.log(p1)-lnncum[i+1]# np.log(poisson.pmf(i+1, p1) / poisson.pmf(0, p1))
        # for j in range(N):
        #     tmp = np.zeros((N),dtype='i')
        #     tmp[j] = i+1
            #print('{},{}:{},{}'.format(i,j,nuxt_root[j,i+1], nusy(y,A,tmp,sig2w,sig2s,mus,p1)))
    pan_root = np.zeros(N)

    # Repeated Greedy Search
    for d in range(D):
        nuxt = nuxt_root.copy()
        z = y.copy()
        cx = cx_root.copy()
        betaxts = betaxts_root.copy()
        pan = pan_root.copy()
        nutemp=0
        for p in range(P):
            # look for duplicates of nu and nuxt, set to -inf.
            # only inspect the same number of PEs in Row p.
            if abs(np.max(nuxt)-nutemp)<1e-2:
                break
            nuxtshadow = np.where(np.sum(np.abs(nuxt - nu[:, :(d+1),np.newaxis,np.newaxis]) < 1e-4, axis=(0,1)), -np.inf, nuxt)
            nustar = np.max(nuxtshadow)
            nutemp = nustar
            #print(nustar)
            assert(~np.isnan(nustar))
            istar = np.argmax(nuxtshadow)
            nu[p, d] = nustar
            T[p, d] = (istar//(1+Q), istar%(1+Q))
            pan[T[p,d][0]] = T[p,d][1]
            istar = T[p,d][0]
            # Eq. (33)
            betaxt = betaxts[istar]
            #cx = cxs[T[p,d][1]-1,:,:]
            #cxs = cx.reshape(1,cx.shape[0],cx.shape[1]) - np.einsum('qn,y,yp->qnp', betaxt.reshape(-1,1) * cx[:, istar], cx[:, istar], A)
            cx = cx - np.einsum('n,m,mp->np', betaxt[T[p,d][1]] * cx[:, istar], cx[:, istar], A)
            # Eq. (34)
            #z = zs[T[p,d][1]-1,:]
            if p==0:
                z = z - A[:, istar] * mus * (T[p,d][1])
            else:
                z = z - A[:, istar] * mus * (T[p,d][1]-xmmse[p-1,d,T[p,d][0]])
            for i in range(p+1):
                xmmse[p, d, T[i,d][0]] = T[i,d][1]
            expectx[p,d] = xmmse[p,d]*mus + sig2s*xmmse[p,d]*np.dot(z,cx)
            #print(xmmse[p,d])
            #print(nustar, nusy(y,A,xmmse[p,d],sig2w,sig2s,mus,p1))
            for i in range(Q+1):
                # Eq. (30)
                selectindex = (i)!=xmmse[p,d,:]
                #betaxts[:,i] = (i+1-xmmse[p,d,:])*sig2s / (1 + (i+1-xmmse[p,d,:])*sig2s * np.sum(A * cxs[i,:,:], axis=0))
                betaxts[:,i] = (i-xmmse[p,d,:])*sig2s / (1 + (i-xmmse[p,d,:])*sig2s * np.sum(A * cx, axis=0))
                betaxt = betaxts[:,i]
                # Eq. (31)
                #nuxt[selectindex,i] = (nustar + 0.5 * (betaxt * (z @ cx + mus / sig2s) ** 2 - 0.5*(i+1-xmmse[p,d,:])*mus ** 2 / sig2s + 0.5*np.log(betaxt/(i+1-xmmse[p,d,:]) / sig2s)) + np.log(poisson.pmf((i+1), mu=p1) / poisson.pmf(xmmse[p,d,:], mu=p1)))[selectindex]
                lnncumL = lnncum[xmmse[p,d,:]]
                #nuxt[selectindex,i] = (nustar + 0.5 * (betaxt * (z @ cxs[i,:,:] + mus / sig2s) ** 2 - 0.5*(i+1-xmmse[p,d,:])*mus ** 2 / sig2s + 0.5*np.log(betaxt/(i+1-xmmse[p,d,:]) / sig2s)) + (i+1-xmmse[p,d,:])*np.log(p1)-(lnncum[i]-lnncumL))[selectindex]
                nuxt[selectindex,i] = (nustar + 0.5 * (betaxt * (z @ cx + mus / sig2s) ** 2 - (i-xmmse[p,d,:])*mus ** 2 / sig2s + np.log(betaxt/(i-xmmse[p,d,:]) / sig2s)) + (i-xmmse[p,d,:])*np.log(p1)-(lnncum[i]-lnncumL))[selectindex]
                nanindex = np.where(np.isnan(nuxt[:,i]))
                nuxt[nanindex,i] = -np.inf
            # nuxt[t] = -np.inf
        #print(p)
        if max(nu[:, d]) > nu_stop:
            d_tot = d + 1
            break
        #print(d)
    nu_bk = nu[:, :d_tot]
    nu = nu[:, :d_tot].T.flatten()

    indx = np.argsort(nu)[::-1]
    d_max = math.floor(indx[0] // P) + 1
    num = min(min(int(np.sum(nu > nu.max() + np.log(psy_thresh))), d_tot * P), 20)
    nu_star = nu[indx[:num]]
    psy_star = np.exp(nu_star - nu.max()) / np.sum(np.exp(nu_star - nu.max()))

    T_star = [sorted(T[:(indx[k] % P) + 1, indx[k] // P],key=lambda t: t[0]) for k in range(num)]
    xmmse_star = np.empty((num, N),dtype='i')
    expectx_star = np.empty((num, N))
    for k in range(num):
        xmmse_star[k] = xmmse[indx[k] % P, indx[k] // P]
        expectx_star[k] = expectx[indx[k] % P, indx[k] // P]
    #print(nu_star)
    xmmse = np.average(xmmse_star, weights=psy_star, axis=0)
    expectx_mean = np.average(expectx_star, weights=psy_star, axis=0)
    return xmmse, xmmse_star, psy_star, nu_star, T_star, d_tot, d_max,expectx_mean, expectx_star

def fbmp_multi_gaussian(y, A, p1, sig2w, sig2s, mus, D, stop=0):
    # Only for multi-gaussian with arithmetic sequence of mu and sigma
    M, N = A.shape

    p = 1 - poisson.pmf(0, p1).mean()
    nu_true_mean = -M / 2 - M / 2 * np.log(sig2w) - p * N / 2 * np.log(sig2s / sig2w + 1) - M / 2 * np.log(2 * np.pi) + N * np.log(1 - p) + p * N * np.log(p / (1 - p))
    nu_true_stdv = np.sqrt(M / 2 + N * p * (1 - p) * (np.log(p / (1 - p)) - np.log(sig2s / sig2w + 1) / 2) ** 2)
    nu_stop = nu_true_mean + stop * nu_true_stdv

    psy_thresh = 1e-3
    P = min(M, 1 + math.ceil(N * p + special.erfcinv(1e-2) * math.sqrt(2 * N * p * (1 - p))))
    # P = math.ceil(min(M, p1.sum() + 3 * np.sqrt(p1.sum())))
    D = min(min(len(p1), P), D)

    T = np.full((P, D), 0)
    nu = np.full((P, D), -np.inf)
    xmmse = np.zeros((P, D, N))
    cc = np.zeros((P, D, N))
    d_tot = D

    nu_root = -0.5 * np.linalg.norm(y) ** 2 / sig2w - 0.5 * M * np.log(2 * np.pi) - 0.5 * M * np.log(sig2w) + np.log(poisson.pmf(0, p1)).sum()
    cx_root = A / sig2w
    betaxt_root = np.abs(sig2s / (1 + sig2s * np.sum(A * cx_root, axis=0)))
    nuxt_root = nu_root + 0.5 * np.log(betaxt_root / sig2s) + 0.5 * betaxt_root * np.abs(np.dot(y, cx_root) + mus / sig2s) ** 2 - 0.5 * mus ** 2 / sig2s + np.log(poisson.pmf(1, p1) / poisson.pmf(0, p1))
    
    for d in range(D):
        nuxt = nuxt_root.copy()
        z = y.copy()
        cx = cx_root.copy()
        betaxt = betaxt_root.copy()
        for p in range(P):
            nuxtshadow = np.where(np.sum(np.abs(nuxt - nu[p, :d][:, None]) < 1e-4, axis=0), -np.inf, nuxt)
            nustar = max(nuxtshadow)
            istar = np.argmax(nuxtshadow)
            nu[p, d] = nustar
            T[p, d] = istar
            cx = cx - np.dot(betaxt[istar] * cx[:, istar].copy().reshape(M, 1), np.dot(cx[:, istar], A).copy().reshape(1, N))

            z = z - A[:, istar] * mus
            assist = np.zeros(N)
            t, c = np.unique(T[:p+1, d], return_counts=True)
            assist[t] = mus * c + sig2s * c * np.dot(z, cx[:, t])
            cc[p, d][t] = c
            xmmse[p, d] = assist
            # poisson
            betaxt = np.abs(sig2s / (1 + sig2s * np.sum(A * cx, axis=0)))
            nuxt = nustar + 0.5 * np.log(betaxt / sig2s) + 0.5 * betaxt * np.abs(np.dot(z, cx) + mus / sig2s) ** 2 - 0.5 * mus ** 2 / sig2s + np.log(poisson.pmf(np.sum(T[:p, d] == istar) + 1, p1[istar]) / poisson.pmf(np.sum(T[:p, d] == istar), p1[istar]))

        if max(nu[:, d]) > nu_stop:
            d_tot = d + 1
            break
    # revise = np.log(poisson.pmf(np.arange(1, P+1), p1.sum())) - special.logsumexp(np.log(poisson.pmf(cc[:, :d_tot], p1)).sum(axis=-1), axis=1)
    # revise = np.log(poisson.pmf(np.arange(1, P+1), p1.sum()))
    # nu[:, :d_tot] = nu[:, :d_tot] + revise[:, None]
    # pp = poisson.pmf(np.arange(1, P+1), p1.sum())
    # nu[:, :d_tot][np.random.uniform(size=nu[:, :d_tot].shape) > pp[:, None] / pp.max()] = -np.inf
    nu = nu[:, :d_tot].T.flatten()

    dum = np.sort(nu)[::-1]
    indx = np.argsort(nu)[::-1]
    d_max = math.floor(indx[0] // P) + 1
    num = min(int(np.sum(nu > nu.max() + np.log(psy_thresh))), D)
    nu_star = nu[indx[:num]]
    psy_star = np.exp(nu_star - nu.max()) / np.sum(np.exp(nu_star - nu.max()))
    T_star = [T[:(indx[k] % P) + 1, indx[k] // P] for k in range(num)]
    xmmse_star = np.empty((num, N))
    for k in range(num):
        xmmse_star[k] = xmmse[indx[k] % P, indx[k] // P]

    xmmse = np.average(xmmse_star, weights=psy_star, axis=0)

    return xmmse, xmmse_star, psy_star, nu_star, T_star, d_tot, d_max
