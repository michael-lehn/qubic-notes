import inspect
import numpy as np

def mark(twidth, dt):
    t=np.arange(0, twidth, dt)
    width=len(t)
    return (t, np.ones(width).astype('int'))

def square(twidth, dt, amplitude=1.0, phase=0.0,alternate_period=None):
    """A simple square pulse"""
    t=np.arange(0, twidth, dt)
    width=len(t)
    env=np.ones(width)*amplitude*np.exp(1j*phase)
    if alternate_period is not None:
        t1,alt=alternate(twidth=twidth,dt=dt,period=alternate_period)
        env=env*alt
    #return (t, (np.ones(width)*amplitude*np.exp(1j*phase)).astype('complex64'))
    return (t, env.astype('complex64'))

def sin(twidth, dt, frequency=0, phase0=0.0):
    """A simple sin pulse"""
    t=np.arange(0, twidth, dt)
    return (t, np.exp(1j * (2.0 * np.pi * frequency * t +phase0 )).astype('complex64'))

def sinf1f2(twidth, dt, frequency1=0, frequency2=0, phase1=0.0, phase2=0.0):
    """Sin pulse with frequency f1 and f2"""
    t=np.arange(0, twidth, dt)
    value1=0.5*np.exp(1j * (2.0 * np.pi * frequency1 * t +phase1 )).astype('complex64')
    value2=0.5*np.exp(1j * (2.0 * np.pi * frequency2 * t +phase2 )).astype('complex64')
    return (t, value1+value2)

def half_sin(twidth , dt, phase0=0.0):
    ' sin(x) for pi in the given width'
    t=np.arange(0, twidth, dt)
    step=1.0/(len(t)-1)
    return (t, np.sin(np.pi * np.arange(0, 1.0+step/2.0, step) ).astype('complex64'))

def gaussian(twidth, dt, sigmas=3):
    """
    Width is the exact width, not the width of the sigmas.
    sigmas is the number of sigma in the width in each side
    """
    #print 'gaussian', twidth, dt, sigmas
    t=np.arange(0, twidth, dt)
    #print len(t), len(np.arange(0, 4e-6, 1e-9))
    width=len(t)
    sigma = width / (2.0 * sigmas)  # (width - 1 )?
    val=np.exp(-(np.arange(0, width) - width / 2.) ** 2. / (2 * sigma ** 2)).astype('complex64')
    #print twidth, dt, width, len(t), len(val)
    #print t, val
    return (t, val)

def DRAG(twidth, dt, sigmas=3, alpha=0.5, delta=-268e6,  df=0):
    """Standard DRAG pulse as defined in https://arxiv.org/pdf/0901.0534.pdf
    Derivative Removal by Adiabatic Gate (DRAG)
    Args:
        width: the total width of the pulse in points
        alpha: alpha parameter of the DRAG pulse 0-3e6 scan 
        sigmas: number of standard deviations
        delta: the anharmonicity of the qubit
        sample_rate: AWG sample rate (default 2.5 GHz), and not used in this method.
        df: additional detuning from target frequency
        """
    #  why use kargs pass that? try use the value directly
    #delta = kargs.get('sample_rate', delta)
    t=np.arange(0, twidth, dt)
    width=len(t)

    sigma = width / (2. * sigmas) #(width - 1)?
    delta = float(delta * 2 * np.pi *dt)
    x = np.arange(0,  width)
    #gaus = np.exp(-(x - width / 2.) ** 2. / (2 * sigma ** 2))
    _, gaus = gaussian(twidth, dt, sigmas)
    dgaus = -(x - width / 2.) / (sigma ** 2) * gaus
    p1=np.exp(1j* x * 1.0*df * dt *  2 * np.pi) 
    p2=(gaus - 1j * alpha * dgaus / delta)
    return (t, (p1*p2).astype('complex64'))

def alternate(twidth,dt,period,mod=2):
    t=np.arange(0, twidth, dt)
    ph=(t//period)%mod*np.pi
    env=np.exp(1j*ph)
    return (t, env.astype('complex64'))

def cos_edge_square(twidth,  dt, ramp_fraction=0.25, ramp_length=None,alternate_period=None):
    if ramp_length is None:
        tedge=np.arange(0, 2*twidth*ramp_fraction, dt)
    else:
        tedge=np.arange(0, 2*ramp_length, dt)
        ramp_fraction=1.0*ramp_length/twidth
    t=np.arange(0, twidth, dt)
    width=len(t)
    if (ramp_fraction>0 and ramp_fraction<=0.5 and twidth>0):
        f=1.0/(2*ramp_fraction*twidth)
        edges=(np.cos(2*np.pi*f*tedge-np.pi)+1.0)/2.0
        #pyplot.plot(edges)
        #pyplot.show()
        nramp=int(len(edges)/2)
        nflat=width-len(edges)
        env=np.concatenate((edges[:nramp], np.ones(nflat), edges[nramp:]))
    else:
        print('ramp_fraction (ramp_length/twidth) should be 0<ramp_function<=0.5, %s and twidth>0 %s'%(str(ramp_fraction), str(twidth)))
        env=np.ones(width)
    if alternate_period is not None:
        t1,alt=alternate(twidth=twidth,dt=dt,period=alternate_period)
        env=env*alt
    return (t, env.astype('complex64'))

def cos_edge(twidth,  dt, ramp_fraction=0.25, ramp_length=None,edge='full'):
    nt=int(twidth//dt)
    if edge=='full':
        phi=np.linspace(-np.pi,np.pi,nt)
    elif edge=='rising':
        phi=np.linspace(-np.pi,0,nt)
    elif edge=='faling':
        phi=np.linspace(0,-np.pi,nt)
    else:
        raise Exception(f'Invalid edge: {edge}. Must be "rising", "falling", or "full"')
    t=np.arange(0,twidth,dt)
    env=np.cos(phi)
    return (t,env.astype('complex64'))

def sin_edge_square(twidth, dt, ramp_fraction=0.25):
    """Return a square pulse shape of the specified amplitude with cosine edges.

    Args:
        width: the total width of the pulse in points
        ramp_fraction: duration of the cosine ramp on either side of the pulse, expressed as a fraction of the total pulse length
        sample_rate: AWG sample rate (default 2.5 GHz), and not used in this method.
        df: additional detuning from target frequency
        """
    t=np.arange(0, twidth, dt)
    width=len(t)
    if (ramp_fraction>0 and ramp_fraction<=0.5):
        _, edges=half_sin(twidth=2*ramp_fraction*twidth, dt=dt, phase0=0.0)
        nramp=int(len(edges)/2)
        nflat=width-len(edges)
        env=np.concatenate((edges[:nramp], np.ones(nflat), edges[nramp:]))
    else:
        print('ramp_fraction should be 0<ramp_function<=0.5 %s'%(str(ramp_fraction)))
        env=np.ones(width)
    # 5.  multiply by a detuning df offset detuning...
  #  df = float(df / sample_rate)
  #  x = np.arange(0, width)
  #  env = env * np.exp(-x * df * 1j * 2 * np.pi)

    return (t, env.astype('complex64'))

def gauss_edge_square(twidth, dt, ramp_fraction=0.1, sigmas=3):
    """Return a square pulse shape of the specified amplitude with gaussian edges.

    Args:
        width: the total width of the pulse in points
        amplitude: the amplitude of the pulse, clipped to between -1 and 1.  
        phase: the phase applied as an overall multipler to the pulse, i.e. pulse_out = pulse * np.exp(1j*phase)
        ramp_fraction: duration of the cosine ramp on either side of the pulse, expressed as a fraction of the total pulse length
    """
    t=np.arange(0, twidth, dt)
    width=len(t)

    if (ramp_fraction>0 and ramp_fraction<=0.5):
        _, edges=gaussian(twidth=2.0*ramp_fraction*twidth, dt=dt, sigmas=sigmas)
        nramp=int(len(edges)/2)
        nflat=width-len(edges)
        #print width, nramp, nflat, len(edges), len(edges[:nramp]), len(np.ones(nflat)), len(edges[nramp:])
        env=np.concatenate((edges[:nramp], np.ones(nflat), edges[nramp:]))
    else:
        print('ramp_fraction should be 0<ramp_function<=0.5 got %s'%(str(ramp_fraction)))
        env=np.ones(width)

    return (t, env.astype('complex64'))


def hann(twidth, dt):
    """A Hann window function, see https://en.wikipedia.org/wiki/Window_function#Hann_window
    """
    t=np.arange(0, twidth, dt)
    width=len(t)
    return  (t, np.hanning(width).astype('complex64'))

def arbcsvfile(twidth, dt, fcsvrealimag, delimiter=', '):
    """An arbitrary pulse definition, allows for arbitrary pulses
    to be added to the sequencer without the creation of new functions.
    """
    realimag=np.loadtxt(fcsvrealimag, delimiter=delimiter)
    t=np.arange(0, twidth, dt)
    width=len(t)
    return (t, (realimag[:, 0]+1j*realimag[:, 1]).astype('complex64'))
def arb(twidth, dt, awgpointsreal, awgpointsimag):
    """An arbitrary pulse definition, allows for arbitrary pulses
    to be added to the sequencer without the creation of new functions.
    """
    t=np.arange(0, twidth, dt)
    width=len(t)
    return (t, np.array(np.array(awgpointsreal[:width])+1j*np.array(awgpointsimag[:width])).astype('complex64'))

def listpulses():
    funcs=inspect.getmembers( predicate=inspect.ismethod)
    funclist=[f for f in funcs if f[0] not in ['__init__', 'listpulses']]
    funclist=[func for func in getmembers(predicate=inspect.ismethod) if func not in ['__init__', 'listpulses']]
    return funclist 

