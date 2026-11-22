#!/usr/bin/env python3
"""Makes the top bar's droplet keyframes (drop-l, drop-t, drop-p, drop-pc) and the search box's spring easing from spring
simulations. Usage: python3 scripts/droplets.py [slow-down factor, default 1.4]; writes /tmp/ux/drop.css to paste into index.html.
Periods and damping per body are in the calls below."""
import math,sys
S=float(sys.argv[1]) if len(sys.argv)>1 else 1.4
def spring(x0,v0,period,zeta,ts):   # returns x(t) for t in ts (seconds), target 0
    w=2*math.pi/period; k=w*w; c=2*zeta*w; x,v,t,out,dt=x0,v0,0.0,[],0.0005
    for T in ts:
        while t<T: a=-k*x-c*v; v+=a*dt; x+=v*dt; t+=dt
        out.append(x)
    return out
def at(fn,ts): return [fn(t) for t in ts]
TOT=0.56*S; N=40; ts=[TOT*i/N for i in range(N+1)]
ms=lambda v:v*S/1000
def edge(A,t_start,t_snap,period,zeta,bulge=None):
    w=2*math.pi/(period*S)
    def f(t):
        if t<t_snap:
            if bulge: return A*min(1,t/ms(50)) if t<ms(50) else A
            if t<t_start: return 0
            u=(t-t_start)/(t_snap-t_start); return A*u*u
        return spring(A,-A*w,period*S,zeta,[t-t_snap])[0]
    return f
def pos(t0,period,zeta):
    def f(t):
        if t<=t0: return 1
        return spring(1,0,period*S,zeta,[t-t0])[0]
    return f
g=lambda v:('%.3f'%v).rstrip('0').rstrip('.') or '0'
def kf(name,rows): return '@keyframes %s{%s}'%(name,''.join('%s%%{%s}'%(g(100*t/TOT),r) for t,r in rows))
out=[]
# language: leading (left) edge fixed, trailing right edge wobbles
pL=pos(ms(50),0.26,0.7); eL=edge(3,ms(120),ms(171),0.26,0.25)
rows=[]
for t in ts:
    w=32+eL(t); rows.append((t,'transform:translateX(calc(var(--tb-x) * %s));scale:%s %s'%(g(pL(t)),g(w/32),g(math.sqrt(32/w)))))
out.append(kf('drop-l',rows))
pT=pos(ms(50),0.30,0.7); eTl=edge(2,ms(120),ms(171),0.23,0.30); eTr=edge(2,ms(160),ms(214),0.23,0.30)
rows=[]
for t in ts:
    l,r=eTl(t),eTr(t); w=32+l+r; rows.append((t,'transform:translateX(calc(var(--tb-x) * %s + %spx));scale:%s %s'%(g(pT(t)),g((r-l)/2),g(w/32),g(math.sqrt(32/w)))))
out.append(kf('drop-t',rows))
eP=edge(2,0,ms(214),0.20,0.35,bulge=True)
out.append(kf('drop-p',[(t,'scale:%s %s'%(g((32+eP(t))/32),g(math.sqrt(32/(32+eP(t)))))) for t in ts]))
# closing: the + swells as each pill is absorbed (150 and 180 ms), then rings
TC=0.46*S; tc=[TC*i/30 for i in range(31)]
def swell(t):
    a,b=ms(150),ms(180)
    if t<ms(110): return 0
    if t<a: return 1.2*(t-ms(110))/(a-ms(110))
    if t<b: return 1.2+1.3*(t-a)/(b-a)
    w=2*math.pi/(0.2*S); return spring(2.5,-2.5*w,0.2*S,0.35,[t-b])[0]
out.append('@keyframes drop-pc{%s}'%''.join('%s%%{scale:%s %s}'%(g(100*t/TC),g((32+swell(t))/32),g(math.sqrt(32/(32+swell(t))))) for t in tc))
# the search box edge: a spring as a linear() easing
def lin(period,zeta,dur):
    n=24; xs=spring(1,0,period*S,zeta,[dur*i/n for i in range(n+1)]); return 'linear(%s)'%','.join(g(1-x) for x in xs)
vars_=dict(TOT=g(TOT),TC=g(TC),boxo=lin(0.32,0.7,0.48*S),boxod=g(0.48*S),boxc=lin(0.30,0.8,0.42*S),boxcd=g(0.42*S),
  d40=g(ms(40)),bl=g(ms(140)),bt=g(ms(110)),d60=g(ms(60)),icon=g(ms(150)))
css='''/* droplets, second take (22 Nov 2026): one drop parting into three at about a fifth of real speed. Each body keeps its own
   clock (the + 5 Hz, appearance 4.3, language 3.8, the box 3.1, all slowed by the same factor) so they never move in step; the
   stretch is along the bar, with the height giving way by half as much. Made by scripts in the research notes, not by hand */
%s
.top.tools-open .nav #langBtn{transform-origin:0 50%%;animation:drop-l %ss linear both}
.top.tools-open .nav #themeBtn{transform-origin:50%% 50%%;animation:drop-t %ss linear both}
.top.tools-open .nav #toolsBtn{transform-origin:100%% 50%%;animation:drop-p %ss linear both}
.top.tools-closing .nav #langBtn{animation:tools-back %ss cubic-bezier(.4,0,1,1) %ss both}
.top.tools-closing .nav #themeBtn{animation:tools-back %ss cubic-bezier(.4,0,1,1) %ss both}
.top.tools-closing .nav #toolsBtn{transform-origin:100%% 50%%;animation:drop-pc %ss linear both}
.top:is(.tools-open,.tools-closing) .ask-box{animation:none}   /* the box moves its edge only: its text is never stretched */
@supports (transition-timing-function:linear(0,1)){
  .top.tools-open .ask-line{transition:opacity .25s ease, transform .25s ease, right %ss %s, visibility 0s linear 0s!important}
  .top.tools-closing .ask-line{transition:opacity .25s ease, transform .25s ease, right %ss %s %ss, visibility 0s linear 0s!important}
}
#toolsBtn .tb-v{transition-duration:%ss}
@media (prefers-reduced-motion: reduce){ .top:is(.tools-open,.tools-closing) .nav :is(#langBtn,#themeBtn,#toolsBtn){animation:none!important} .top .ask-line{transition:none!important} }
'''%('\n'.join(out),vars_['TOT'],vars_['TOT'],vars_['TOT'],vars_['bl'],vars_['d40'],vars_['bt'],vars_['d40'],vars_['TC'],vars_['boxod'],vars_['boxo'],vars_['boxcd'],vars_['boxc'],vars_['d60'],vars_['icon'])
open('/tmp/ux/drop.css','w').write(css); print(len(css), 'TOT',TOT,'TC',TC)
