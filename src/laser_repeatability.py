import time
import numpy as np
from picamera2 import Picamera2
from illumination import Lamp

N, EXP, PXMM = 25, 200, 12.71
p = Picamera2()
p.configure(p.create_video_configuration(main={"size": (2304,1296), "format": "YUV420"}))
p.set_controls({"AfMode":0, "LensPosition":7.35, "AwbEnable":False,
                "ColourGains":(1.0,1.0), "AeEnable":False,
                "AnalogueGain":1.0, "ExposureTime":EXP})
p.start(); time.sleep(1.2)
laser = Lamp("laser", 27, settle_s=0.1)

def grab(n=3):
    for _ in range(n): p.capture_array("main")
    return p.capture_array("main")[:1296].astype(np.float32)

laser.shutdown(); time.sleep(0.4); dark = grab(5)
laser.acquire(); time.sleep(0.5)
xs, ys, rs = [], [], []
for i in range(N):
    d = grab() - dark
    pk = d.max(); m = d >= pk*0.2
    yy, xx = np.nonzero(m); w = d[yy, xx]
    cx = (xx*w).sum()/w.sum(); cy = (yy*w).sum()/w.sum()
    xs.append(cx); ys.append(cy)
    rs.append(((cx-1152)**2 + (cy-648)**2) ** 0.5)
laser.shutdown(); p.stop()

xs, ys, rs = np.array(xs), np.array(ys), np.array(rs)
print(f"{N} mätningar vid {EXP} us\n")
print(f"x:  medel {xs.mean():8.2f}  std {xs.std():.3f} px")
print(f"y:  medel {ys.mean():8.2f}  std {ys.std():.3f} px")
print(f"r:  medel {rs.mean():8.2f}  std {rs.std():.3f} px   spann {rs.max()-rs.min():.3f} px")
print()
print(f"radiens std i objektrymd: {rs.std()/PXMM*1000:.0f} um")
print(f"vid 1.50 px/mm ger det hojdupplosning {rs.std()/1.50*1000:.0f} um")
print(f"briefingen forutsade 300-500 um")
