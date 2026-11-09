#!/usr/bin/env python3
"""Run every canode rev A analog simulation (validation step 6) and print the key numbers.

    source .venv/bin/activate
    python validation/sim/run_all.py            # all sims, plots to validation/sim/out/
    python validation/sim/run_all.py --no-plots

Needs ngspice (tested with 47) and numpy (+ matplotlib for plots). Vendor models are
fetched by fetch_models.sh on first run (they are not committed; see that script).

Each *.cir in this directory is a plain ngspice netlist with .param defaults; this script
copies it to out/, overrides .params per case, appends a .control block that writes the
traces with wrdata, then post-processes the data with numpy. Exit status is 0 even when a
verdict is FAIL: the verdicts are findings, not script errors.
"""
from __future__ import annotations

import argparse
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

SIM = Path(__file__).resolve().parent
OUT = SIM / "out"
NGSPICE = shutil.which("ngspice") or "/opt/homebrew/bin/ngspice"

# --------------------------------------------------------------------------- limits used
LIM = dict(
    ptc_vmax=30.0,      # F1 BSMD1206-050-30V rated voltage
    ptc_imax=40.0,      # F1 max interrupt current
    q1_vds=30.0,        # AO3400A VDS abs max
    q1_is=2.0,          # AO3400A body diode continuous current
    ldo_op=40.0,        # TPS7B69 recommended max VI
    ldo_abs=45.0,       # TPS7B69 abs max VI ("withstands 45 V for 200 ms")
    ss34_vr=40.0,       # SS34 VRRM
    tvs_ppk=600.0,      # SMBJ peak pulse power, 10/1000 us
    tvs_ifsm=100.0,     # SMBJ forward surge, 8.3 ms half sine
    vdd=3.3,
    ft_abs=3.3 + 4.0,   # STM32G0 FT_xx abs max VIN = VDDIO + 4.0 V
    ft_op=5.5,          # FT pins, normal operation max (min(VDD+3.6, 5.5))
    adc_fs=3.3,
)
# SMBJ 600 W @ 10/1000 us: energy = 600 W * 1 ms/ln2 = 0.866 J over an equivalent ~1.44 ms.
# Longer pulses: allowable energy scaled with sqrt(t) (adiabatic diffusion). This is an
# OPTIMISTIC extrapolation of the datasheet Ppk-vs-td curve beyond 10 ms; exceeding it is a
# clear fail, staying under it is not proof of survival.
TVS_E_REF, TVS_T_REF = 600.0 * 1e-3 / math.log(2), 1e-3 / math.log(2)


def tvs_e_allow(t_eff: float) -> float:
    return TVS_E_REF * math.sqrt(max(t_eff, 1e-6) / TVS_T_REF)


# --------------------------------------------------------------------------- ngspice glue
def ensure_models() -> None:
    need = ["ss34.txt", "TPS7B6933-Q1_TRANS.lib", "smbj22a.txt", "smbj33a.txt"]
    if all((SIM / "models" / "vendor" / n).exists() for n in need):
        return
    print("fetching vendor models ...")
    subprocess.run([str(SIM / "fetch_models.sh")], check=True)


def compose(cir: str, params: dict, control: str, subs: dict | None = None) -> str:
    text = (SIM / cir).read_text()
    for k, v in params.items():
        pat = re.compile(rf"(^\.param\b[^\n]*?\b{k}\s*=\s*)([^\s]+)", re.M | re.I)
        text, n = pat.subn(lambda m: m.group(1) + str(v), text)
        if n != 1:
            raise KeyError(f"{cir}: .param {k} found {n} times")
    # inline board.inc so that model substitutions (subs) reach the board netlist too
    text = text.replace(".include board.inc", (SIM / "board.inc").read_text())
    for a, b in (subs or {}).items():
        if a not in text:
            raise KeyError(f"{cir}: substitution target {a!r} not found")
        text = text.replace(a, b)
    text = re.sub(r"^\.end\s*$", "", text, flags=re.M)
    return text + "\n.control\n" + control + "\nquit\n.endc\n.end\n"


def run(tag: str, cir: str, params: dict, vecs: list[str], analysis: str = "run",
        subs: dict | None = None) -> dict[str, np.ndarray]:
    dat = OUT / f"{tag}.dat"
    control = "\n".join([
        "set wr_singlescale", "set wr_vecnames", "option numdgt=7",
        analysis,
        f"wrdata {dat} " + " ".join(vecs),
    ])
    net = OUT / f"{tag}.cir"
    net.write_text(compose(cir, params, control, subs))
    p = subprocess.run([NGSPICE, "-D", "ngbehavior=ps", "-b", str(net)], cwd=SIM,
                       capture_output=True, text=True, timeout=900)
    (OUT / f"{tag}.log").write_text(p.stdout + p.stderr)
    log = p.stdout + p.stderr
    if p.returncode != 0 or not dat.exists() or "aborted" in log or "too small" in log:
        raise RuntimeError(f"ngspice failed for {tag}; see {OUT / (tag + '.log')}")
    with dat.open() as f:
        names = f.readline().split()
    data = np.loadtxt(dat, skiprows=1)
    return {n.lower(): data[:, i] for i, n in enumerate(names)}


def integ(y, t):
    return float(np.trapezoid(y, t)) if hasattr(np, "trapezoid") else float(np.trapz(y, t))


def first_time(t, mask):
    idx = np.flatnonzero(mask)
    return float(t[idx[0]]) if idx.size else None


def dur(t, mask):
    """total time where mask is true"""
    dt = np.diff(t, append=t[-1])
    return float(np.sum(dt[mask]))


def fmt(x, unit="", nd=2):
    if x is None:
        return "-"
    return f"{x:.{nd}f}{unit}"


# --------------------------------------------------------------------------- model checks
def model_checks() -> list[str]:
    """PTC trip calibration and TVS model vs Vishay vendor models (inline netlists)."""
    lines = []
    # PTC: time-to-trip at 8 A (datasheet max 0.1 s), and hold/trip behavior at 0.5 / 1.0 A
    for corner, cth in (("slow", 0.032), ("fast", 0.010)):
        for i_test, tstop in ((8.0, 0.3), (1.0, 60.0), (0.5, 60.0)):
            net = OUT / f"cal_ptc_{corner}_{i_test:g}A.cir"
            net.write_text(f"""* PTC calibration
.include models/canode.lib
I1 0 a PWL(0 0 1u {i_test})
* compliance: a 1 A test is done from a 24 V / 20 ohm-ish source in practice; here a current
* source with a 30 V clamp so the tripped state is well defined
Dclamp a c DCL
Vclamp c 0 30
.model DCL D(IS=1e-12 N=1)
X1 a 0 tj PTC_BSMD1206 PARAMS: r25=0.25 cth={cth}
.tran 1m {tstop} 0 {tstop/2000}
.control
set wr_singlescale
set wr_vecnames
run
wrdata {OUT}/cal_ptc_{corner}_{i_test:g}A.dat v(tj) v(a)
quit
.endc
.end
""")
            subprocess.run([NGSPICE, "-b", str(net)], cwd=SIM, capture_output=True, timeout=300)
            d = np.loadtxt(OUT / f"cal_ptc_{corner}_{i_test:g}A.dat", skiprows=1)
            t, tj = d[:, 0], d[:, 1]
            ttrip = first_time(t, tj > 115)
            lines.append(f"PTC {corner:4s} corner @ {i_test:>4g} A: "
                         + (f"trips at {ttrip*1e3:.1f} ms" if ttrip else
                            f"holds, Tj settles {tj[-1]:.0f} degC"))
    # TVS: generic SMBJ_UNI vs Vishay models; SMBJ24A fit vs datasheet VC
    cases = [
        ("SMBJ22A", "smbj22a", 25.65, 0.5725, 16.9, 35.5),
        ("SMBJ33A", "smbj33a", 38.65, 1.285, 11.3, 53.3),
        ("SMBJ24A", None, 28.1, 0.70, 15.4, 38.9),
    ]
    for name, vend, vbr, rd, ipp, vc in cases:
        net = OUT / f"cal_tvs_{name}.cir"
        vend_inc = f".include models/vendor/{vend}.txt\nXV 0 kv {vend}\nIV 0 kv DC 0\n" if vend else ""
        net.write_text(f"""* TVS check
.include models/canode.lib
{vend_inc}XG 0 kg SMBJ_UNI PARAMS: vbr={vbr} rd={rd}
IG 0 kg DC 0
.control
set wr_singlescale
foreach ival 1e-3 1 5 {ipp}
  alter IG dc = $ival
  {"alter IV dc = $ival" if vend else ""}
  op
  let vg = v(kg)
  {"let vv = v(kv)" if vend else ""}
  echo "I=$ival VG=$&vg {"VV=$&vv" if vend else ""}"
end
quit
.endc
.end
""")
        p = subprocess.run([NGSPICE, "-b", str(net)], cwd=SIM, capture_output=True, text=True, timeout=60)
        rows = [l for l in p.stdout.splitlines() if l.startswith("I=")]
        parts = []
        for r in rows:
            kv = dict(x.split("=") for x in r.split())
            s = f"{float(kv['I']):g} A: {float(kv['VG']):.2f} V"
            if "VV" in kv:
                s += f" (Vishay {float(kv['VV']):.2f})"
            parts.append(s)
        lines.append(f"TVS {name} model ({'generic vs Vishay' if vend else 'fit'}; datasheet VC "
                     f"{vc} V @ {ipp} A): " + "; ".join(parts))
    return lines


# --------------------------------------------------------------------------- sim 1
RB_VECS = ["v(vbat_in)", "v(vbatf)", "v(vin)", "v(p3v3)", "v(vbat_sense)", "v(aux_sense)",
           "v(aux_out)", "v(f1_tj)", "i(vif1)", "i(vid3)", "i(vid7)", "i(viq1)"]


def sim_reverse(plots: bool) -> tuple[list[dict], dict]:
    cases = [
        ("rb_slow", "no AUX load, PTC slow corner (0.1 s @ 8 A)", dict(ptc_cth=0.032)),
        ("rb_fast", "no AUX load, PTC fast corner", dict(ptc_cth=0.010)),
        ("rb_stiff", "stiff source (20 mohm total), PTC slow", dict(ptc_cth=0.032, rsrc=0.02)),
        ("rb_relay", "85 ohm / 0.2 H relay on AUX_OUT", dict(ptc_cth=0.032, rload=85, lload=0.2)),
        ("rb_lamp", "12 ohm lamp on AUX_OUT", dict(ptc_cth=0.032, rload=12, lload=1e-6)),
        ("rb_rd7", "what-if: 2.2 ohm in series with D7, PTC slow", dict(ptc_cth=0.032, rd7=2.2)),
    ]
    res, keep = [], {}
    for tag, desc, prm in cases:
        d = run(tag, "reverse_battery.cir", prm, RB_VECS)
        t = d["time"]
        ip = -d["i(vif1)"]                      # reverse fault current magnitude through F1
        itvs = -d["i(vid3)"]                    # TVS forward current
        iq1 = -d["i(viq1)"]                     # Q1 body diode current (source->drain)
        id7 = d["i(vid7)"]
        vptc = d["v(vbatf)"] - d["v(vbat_in)"]  # positive when reverse current flows
        ttrip = first_time(t, d["v(f1_tj)"] > 115)
        i2t = integ(ip ** 2 * (t < (ttrip or t[-1]) + 5e-3), t)
        tvs_e = integ(np.clip(itvs, 0, None) * np.clip(-d["v(vbatf)"], 0, None), t)
        pq1 = np.clip(iq1, 0, None) * np.clip(-d["v(aux_out)"], 0, None)
        r = dict(
            tag=tag, desc=desc,
            ipk=ip.max(), ttrip=ttrip, i2t=i2t,
            itvs_pk=itvs.max(), tvs_e=tvs_e,
            iq1_pk=iq1.max(), iq1_end=iq1[-1], id7_pk=id7.max(), pq1_pk=pq1.max(),
            eq1=integ(pq1 * (t < (ttrip or t[-1]) + 5e-3), t),
            vptc_end=vptc[-1], vptc_pk=vptc.max(), ileak_end=ip[-1],
            vmin={k: d[f"v({k})"].min() for k in
                  ("vbatf", "vin", "p3v3", "vbat_sense", "aux_sense", "aux_out")},
        )
        res.append(r)
        keep[tag] = d
    if plots:
        plot_traces(keep["rb_slow"], "Reverse battery (-14 V, 50 mohm source, PTC slow corner)",
                    OUT / "sim1_reverse_battery.png",
                    [("v(vbat_in)", "VBAT_IN (J2-1)"), ("v(vbatf)", "VBATF"), ("v(vin)", "VIN (LDO in)"),
                     ("v(aux_out)", "AUX_OUT")],
                    [("-i(vif1)", "F1 current"), ("-i(vid3)", "D3 TVS fwd current"),
                     ("-i(viq1)", "Q1 body diode")], xlim=(0, 0.03), tscale=1e3)
    return res, keep


# --------------------------------------------------------------------------- sim 2
LD_VECS = ["v(bus)", "v(vbat_in)", "v(vbatf)", "v(vin)", "v(p3v3)", "v(vbat_sense)",
           "v(aux_sense)", "v(aux_out)", "v(aux_in)", "v(f1_tj)", "i(vif1)", "i(vid3)",
           "i(vid7)", "i(viq1)"]
RELAY = dict(rload=85, lload=0.2)
LAMP = dict(rload=24, lload=1e-6)
SMBJ33A = dict(tvs_vbr=38.65, tvs_rd=1.30)
SMBJ36A = dict(tvs_vbr=42.1, tvs_rd=1.54)
UNSUP = dict(us=87, ri=1, ustar=1000, td=0.3, tstop=0.325)   # stop 5 ms after the pulse: see report
SUP = dict(us=87, ri=0.5, ustar=35, td=0.4, tstop=0.425)
P2A = dict(us=13.5 + 112, ri=2, ustar=1000, shape=1, tr=1e-6, td=50e-6, t0=0.001, tstop=0.0015, tmax=0.2e-6)


def ld_cases():
    c = [
        # group, tag, description, params, subs
        ("A", "ldA_slow", "87 V/1 ohm 300 ms flat, no AUX load, PTC slow", dict(UNSUP, ptc_cth=0.032), None),
        ("A", "ldA_fast", "87 V/1 ohm 300 ms flat, no AUX load, PTC fast", dict(UNSUP, ptc_cth=0.010), None),
        ("A", "ldA_iso", "87 V/1 ohm ISO shape (tr 10 ms, td 300 ms), PTC slow",
         dict(UNSUP, shape=1, tr=0.01, ptc_cth=0.032), None),
        ("A", "ldA_relay", "unsuppressed + 85 ohm relay on AUX_OUT (Q1 off)", dict(UNSUP, **RELAY), None),
        ("A", "ldA_lamp", "unsuppressed + 24 ohm load on AUX_OUT (Q1 off)", dict(UNSUP, **LAMP), None),
        ("A", "ldA_lamp_rd7", "unsuppressed + 24 ohm load, 2.2 ohm in series with D7", dict(UNSUP, **LAMP, rd7=2.2), None),
        ("A", "ldA_33A", "what-if D3 = SMBJ33A, unsuppressed, PTC slow", dict(UNSUP, **SMBJ33A), None),
        ("B", "ldB_slow", "35 V clamp/0.5 ohm 400 ms, no AUX load, PTC slow", dict(SUP, ptc_cth=0.032), None),
        ("B", "ldB_fast", "35 V clamp/0.5 ohm 400 ms, no AUX load, PTC fast", dict(SUP, ptc_cth=0.010), None),
        ("B", "ldB_ri1", "35 V clamp/1 ohm 400 ms, PTC slow", dict(SUP, ri=1), None),
        ("B", "ldB_ri4", "35 V clamp/4 ohm 400 ms, PTC slow", dict(SUP, ri=4), None),
        ("B", "ldB_vbrmin", "35 V/0.5 ohm, D3 at VBR min (26.7 V)", dict(SUP, tvs_vbr=26.7, tvs_rd=0.79), None),
        ("B", "ldB_relay", "35 V/0.5 ohm + 85 ohm relay on AUX_OUT (Q1 off)", dict(SUP, **RELAY), None),
        ("B", "ldB_relay_bv31", "as above, Q1 avalanche at 31 V (low-BV part)", dict(SUP, **RELAY),
         {"AO3400A_FIT": "AO3400A_BV31"}),
        # ISO 7637-2 pulse 2a, highest level: +112 V on 13.5 V, Ri 2 ohm, tr 1 us, td 50 us
        ("P", "p2a_24A", "pulse 2a 112 V/2 ohm, as built (SMBJ24A)", dict(P2A), None),
        ("P", "p2a_33A", "pulse 2a, D3 = SMBJ33A", dict(P2A, **SMBJ33A), None),
        ("P", "p2a_33A_rc", "pulse 2a, SMBJ33A + 10 ohm D1->VIN + C1 = 10 uF (8 uF eff.)",
         dict(P2A, **SMBJ33A, rvin=10, c1eff=8e-6), None),
        ("P", "p2a_24A_relay55", "pulse 2a, as built D3, relay on AUX_OUT, Q1 = 55 V FET",
         dict(P2A, **RELAY), {"AO3400A_FIT": "NFET_55V_OFF"}),
        ("P", "p2a_33A_relay55", "pulse 2a, D3 = SMBJ33A, relay on AUX_OUT, Q1 = 55 V FET",
         dict(P2A, **SMBJ33A, **RELAY), {"AO3400A_FIT": "NFET_55V_OFF"}),
        ("P", "p2a50_24A", "pulse 2a at 50 V (lower OEM level), as built", dict(P2A, us=63.5), None),
        ("N", "fly_relay", "13.5 V, relay ON then Q1 turned off (normal flyback)",
         dict(us=13.5, aux_drv=3.3, toff=0.05, tstop=0.1, **RELAY), None),
        ("N", "fly_relay_rd7", "as above with 2.2 ohm in series with D7",
         dict(us=13.5, aux_drv=3.3, toff=0.05, tstop=0.1, rd7=2.2, **RELAY), None),
        ("B", "ldB_33A", "what-if D3 = SMBJ33A, 35 V/0.5 ohm, relay on AUX_OUT", dict(SUP, **SMBJ33A, **RELAY), None),
        ("B", "ldB_33A_55V", "what-if D3 = SMBJ33A + Q1 55 V FET, 35 V/0.5 ohm, relay", dict(SUP, **SMBJ33A, **RELAY),
         {"AO3400A_FIT": "NFET_55V_OFF"}),
        ("B", "ldB_36A", "what-if D3 = SMBJ36A, 35 V/0.5 ohm, relay on AUX_OUT", dict(SUP, **SMBJ36A, **RELAY), None),
    ]
    return c


def sim_loaddump(plots: bool) -> tuple[list[dict], dict]:
    res, keep = [], {}
    for grp, tag, desc, prm, subs in ld_cases():
        d = run(tag, "loaddump.cir", prm, LD_VECS, subs=subs)
        t = d["time"]
        ev = t > prm.get("t0", 0.02) - 1e-3             # ignore the pre-pulse steady state
        vptc = d["v(vbat_in)"] - d["v(vbatf)"]
        iptc = d["i(vif1)"]
        itvs = d["i(vid3)"]
        ptvs = np.clip(itvs, 0, None) * d["v(vbatf)"]
        e_tvs = integ(ptvs, t)
        t_eff = e_tvs / ptvs.max() if ptvs.max() > 0 else 0.0
        vq = d["v(aux_out)"]
        iq = d["i(viq1)"]
        pq = np.clip(iq, 0, None) * np.clip(vq, 0, None)
        e_q1 = integ(pq * (vq > LIM["q1_vds"]), t)
        ttrip = first_time(t, d["v(f1_tj)"] > 115)
        t0 = prm.get("t0", 0.02)
        r = dict(
            grp=grp, tag=tag, desc=desc,
            vbus_pk=d["v(bus)"].max(),
            vbatf_pk=d["v(vbatf)"].max(), vin_pk=d["v(vin)"].max(),
            t_vin40=dur(t, d["v(vin)"] > LIM["ldo_op"]), t_vin45=dur(t, d["v(vin)"] > LIM["ldo_abs"]),
            vq1_pk=vq.max(), t_vq1_30=dur(t, vq > LIM["q1_vds"]), iq1_pk=np.clip(iq, 0, None).max(),
            pq1_pk=pq.max(), e_q1=e_q1, id7_pk=d["i(vid7)"].max(),
            iptc_pk=iptc[ev].max(), ttrip=(ttrip - t0) if ttrip else None,
            vptc_pk=vptc.max(), t_vptc30=dur(t, vptc > LIM["ptc_vmax"]),
            itvs_pk=itvs.max(), ptvs_pk=ptvs.max(), e_tvs=e_tvs, t_eff=t_eff,
            e_allow=tvs_e_allow(t_eff) if e_tvs > 1e-3 else None,
            vsense_pk=d["v(vbat_sense)"].max(), vauxs_pk=d["v(aux_sense)"].max(),
            p3v3_min=d["v(p3v3)"][ev].min(), p3v3_max=d["v(p3v3)"].max(),
        )
        res.append(r)
        keep[tag] = d
    if plots:
        for tag, title, fn, xmax in (
            ("ldA_slow", "Unsuppressed load dump: 87 V / 1 ohm, 300 ms (PTC slow corner)", "sim2_loaddump_unsuppressed.png", 0.325),
            ("ldB_relay", "Suppressed load dump: 35 V / 0.5 ohm, 400 ms, relay on AUX_OUT", "sim2_loaddump_suppressed.png", 0.425),
        ):
            d = keep[tag]
            d["vptc"] = d["v(vbat_in)"] - d["v(vbatf)"]
            plot_traces(d, title, OUT / fn,
                        [("v(bus)", "vehicle bus (after Ri)"), ("v(vbatf)", "VBATF"), ("v(vin)", "VIN (LDO)"),
                         ("v(aux_out)", "AUX_OUT = Q1 VDS"), ("vptc", "voltage across F1")],
                        [("i(vif1)", "F1 current"), ("i(vid3)", "D3 TVS current")],
                        xlim=(0, xmax), tscale=1e3, hlines=[(30, "30 V (F1, Q1 rating)"), (45, "45 V (LDO abs max)")])
    return res, keep


# --------------------------------------------------------------------------- sim 3
def sim_divider(plots: bool, ld: list[dict]) -> dict:
    d = run("div_dc", "vbat_divider.cir", {}, ["v(vbat_sense)", "v(vbatf)"], analysis="dc VSUP 0 26 0.1")
    vs, vadc = d["v-sweep"] if "v-sweep" in d else d[list(d)[0]], d["v(vbat_sense)"]
    pts = {}
    for v in (9, 12, 13.5, 14.4, 16, 24):
        a = float(np.interp(v, vs, vadc))
        pts[v] = (a, min(4095, round(a / LIM["adc_fs"] * 4096)))
    # transient settling to 0.5 LSB for a 0 -> 14 V step
    tr = run("div_step", "vbat_divider.cir", dict(vstep=14), ["v(vbat_sense)"])
    t, v = tr["time"], tr["v(vbat_sense)"]
    final = v[-1]
    lsb = LIM["adc_fs"] / 4096
    outside = np.flatnonzero(np.abs(v - final) > lsb / 2)
    t_settle = float(t[outside[-1]] - 1e-3) if outside.size else 0.0
    t_63 = first_time(t, v > 0.632 * final) - 1e-3
    res = dict(points=pts, t_settle=t_settle, t_63=t_63, final=final, gain=float(np.polyfit(vs[(vs > 1) & (vs < 24)], vadc[(vs > 1) & (vs < 24)], 1)[0]),
               ld={r["tag"]: (r["vbatf_pk"], r["vsense_pk"], r["vauxs_pk"]) for r in ld})
    if plots:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(1, 2, figsize=(11, 4))
        ax[0].plot(vs, vadc, color="#2a6fbb")
        ax[0].axhline(LIM["vdd"] + 0.3, color="#c0392b", ls="--", lw=1, label="VDD + 0.3 V")
        ax[0].axhline(LIM["adc_fs"], color="#7f8c8d", ls=":", lw=1, label="ADC full scale (3.3 V)")
        ax[0].set_xlabel("VBAT_IN (V)"); ax[0].set_ylabel("PA0 (V)"); ax[0].set_title("VBAT divider transfer")
        ax[0].legend(); ax[0].grid(alpha=.3)
        ax[1].plot((t - 1e-3) * 1e3, v, color="#2a6fbb")
        ax[1].set_xlabel("time after 0->14 V step (ms)"); ax[1].set_ylabel("PA0 (V)")
        ax[1].set_title(f"Settling: 0.5 LSB after {t_settle*1e3:.1f} ms"); ax[1].grid(alpha=.3)
        fig.tight_layout(); fig.savefig(OUT / "sim3_vbat_divider.png", dpi=110); plt.close(fig)
    return res


# --------------------------------------------------------------------------- sim 4
ST_VECS = ["v(vbat_in)", "v(vbatf)", "v(vin)", "v(vbus)", "v(p3v3)", "i(vif1)", "i(vid1)"]


def sim_startup(plots: bool) -> list[dict]:
    cases = [
        ("st_hot12", "12 V hot-plug at J2 (1 uH lead)", dict(src=0, tstop=0.006)),
        ("st_hot12_3u", "12 V hot-plug, 3 uH lead (~3 m harness)", dict(src=0, lh=3e-6, tstop=0.006)),
        ("st_usb", "USB 5 V hot-plug", dict(src=1, tstop=0.006)),
        ("st_ramp", "12 V slow ramp (10 ms)", dict(src=2, tstop=0.02)),  # metrics after 12 ms
        ("st_crank45", "crank dip 13.5 -> 4.5 V, 30 ms", dict(src=3, vdip=4.5, tstop=0.06)),
        ("st_crank60", "start-stop dip 13.5 -> 6.0 V, 30 ms", dict(src=3, vdip=6.0, tstop=0.06)),
    ]
    res, keep = [], {}
    for tag, desc, prm in cases:
        d = run(tag, "ldo_startup.cir", prm, ST_VECS)
        t, vo = d["time"], d["v(p3v3)"]
        t10, t90, t30 = (first_time(t, vo > x) for x in (0.33, 2.97, 3.0))
        r = dict(tag=tag, desc=desc, vin_pk=d["v(vin)"].max(), vbatf_pk=d["v(vbatf)"].max(),
                 vbus_pk=d["v(vbus)"].max(), i_in_pk=max(d["i(vif1)"].max(), 0), id1_pk=d["i(vid1)"].max(),
                 t_rise=(t90 - t10) if (t10 and t90) else None, t_30=(t30 - 1e-3) if t30 else None,
                 vo_max=vo.max(), vo_min=vo[t > (12e-3 if tag == "st_ramp" else 2e-3)].min(),
                 vin_min=d["v(vin)"][t > (12e-3 if tag == "st_ramp" else 2e-3)].min())
        # datasheet worst-case dropout (0.8 V) instead of the model's 4.66 ohm switch
        r["vo_min_ds"] = min(3.3, r["vin_min"] - 0.8)
        res.append(r)
        keep[tag] = d
    if plots:
        plot_traces(keep["st_hot12"], "LDO start-up: 12 V hot-plug at J2 (1 uH lead)", OUT / "sim4_ldo_startup.png",
                    [("v(vbat_in)", "VBAT_IN"), ("v(vin)", "VIN (LDO in)"), ("v(p3v3)", "+3V3")],
                    [("i(vif1)", "input current (F1)")], xlim=(0.9, 2.2), tscale=1e3)
    return res


# --------------------------------------------------------------------------- plotting
def plot_traces(d, title, path, vtraces, itraces, xlim=None, tscale=1.0, hlines=()):
    import matplotlib.pyplot as plt
    t = d["time"] * tscale
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 6.5), sharex=True, gridspec_kw=dict(height_ratios=[3, 2]))
    palette = ["#2a6fbb", "#e67e22", "#27ae60", "#8e44ad", "#c0392b", "#16a085"]

    def get(name):
        return -d[name[1:]] if name.startswith("-") else d[name]
    for i, (n, lab) in enumerate(vtraces):
        a1.plot(t, get(n), label=lab, color=palette[i % len(palette)], lw=1.3)
    for y, lab in hlines:
        a1.axhline(y, color="#7f8c8d", ls="--", lw=0.9)
        a1.text(xlim[1] * tscale if xlim else t[-1], y, lab + " ",
                va="bottom", ha="right", fontsize=8, color="#555")
    for i, (n, lab) in enumerate(itraces):
        a2.plot(t, get(n), label=lab, color=palette[(i + 3) % len(palette)], lw=1.3)
    a1.set_ylabel("V"); a2.set_ylabel("A"); a2.set_xlabel("time (ms)" if tscale == 1e3 else "time (s)")
    a1.set_title(title); a1.legend(fontsize=8, loc="best"); a2.legend(fontsize=8, loc="best")
    for a in (a1, a2):
        a.grid(alpha=.3)
        if xlim:
            a.set_xlim(xlim[0] * tscale, xlim[1] * tscale)
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


# --------------------------------------------------------------------------- report
def verdict(ok, concern=False):
    return "PASS" if ok else ("CONCERN" if concern else "FAIL")


class Tee:
    """print to the terminal and to out/summary.txt"""
    def __init__(self, path):
        self.f, self.o = open(path, "w"), sys.stdout

    def write(self, x):
        self.o.write(x); self.f.write(x)

    def flush(self):
        self.o.flush(); self.f.flush()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-plots", action="store_true")
    a = ap.parse_args()
    plots = not a.no_plots
    if plots:
        try:
            import matplotlib
            matplotlib.use("Agg")
        except ImportError:
            print("matplotlib not installed: skipping plots")
            plots = False
    OUT.mkdir(exist_ok=True)
    ensure_models()
    sys.stdout = Tee(OUT / "summary.txt")

    print("=== model checks")
    for l in model_checks():
        print("  " + l)

    print("\n=== sim 1: reverse battery (-14 V at J2-1)")
    rb, _ = sim_reverse(plots)
    for r in rb:
        vm = r["vmin"]
        print(f"  [{r['tag']}] {r['desc']}")
        print(f"     F1 peak {r['ipk']:.1f} A (Imax {LIM['ptc_imax']:.0f}), trips {fmt(r['ttrip'] and r['ttrip']*1e3 - 1, ' ms', 1)} "
              f"after reversal, I2t {r['i2t']:.2f} A2s; TVS fwd peak {r['itvs_pk']:.1f} A, {r['tvs_e']:.2f} J")
        print(f"     Q1 body diode peak {r['iq1_pk']:.2f} A / {r['pq1_pk']:.1f} W, {r['eq1']*1e3:.0f} mJ until trip (end {r['iq1_end']:.2f} A), D7 peak {r['id7_pk']:.2f} A; "
              f"F1 after trip: {r['vptc_end']:.1f} V across it, {r['ileak_end']*1e3:.0f} mA")
        print("     minima: " + ", ".join(f"{k} {v:.2f} V" for k, v in vm.items()))

    print("\n=== sim 2: load dump (Q1 off)")
    ld, _ = sim_loaddump(plots)
    for grp, name in (("A", "TEST A: UNSUPPRESSED"), ("B", "TEST B: SUPPRESSED (35 V)"),
                      ("P", "ISO 7637-2 PULSE 2a (supplementary, for the TVS choice)"),
                      ("N", "NORMAL 13.5 V: AUX_OUT relay turn-off")):
        print(f"  --- {name}")
        for r in (x for x in ld if x["grp"] == grp):
            print(f"  [{r['tag']}] {r['desc']}")
            print(f"     VBATF pk {r['vbatf_pk']:.1f} V | VIN pk {r['vin_pk']:.1f} V (>40 V {r['t_vin40']*1e3:.1f} ms, >45 V {r['t_vin45']*1e3:.1f} ms)"
                  f" | bus pk {r['vbus_pk']:.1f} V")
            print(f"     F1: Ipk {r['iptc_pk']:.1f} A, trip {fmt(r['ttrip'] and r['ttrip']*1e3, ' ms', 1)}, "
                  f"Vpk across F1 {r['vptc_pk']:.1f} V (>30 V for {r['t_vptc30']*1e3:.0f} ms)")
            ea = r["e_allow"]
            print(f"     D3: Ipk {r['itvs_pk']:.1f} A, Ppk {r['ptvs_pk']:.0f} W, E {r['e_tvs']:.2f} J over t_eff {r['t_eff']*1e3:.1f} ms"
                  + (f" (allow ~{ea:.2f} J -> {r['e_tvs']/ea:.1f}x)" if ea else ""))
            print(f"     Q1: VDS pk {r['vq1_pk']:.1f} V (>30 V {r['t_vq1_30']*1e3:.0f} ms), Id pk {r['iq1_pk']:.2f} A, "
                  f"Ppk {r['pq1_pk']:.1f} W, E(>30 V) {r['e_q1']:.2f} J; D7 pk {r['id7_pk']:.2f} A")
            print(f"     PA0 pk {r['vsense_pk']:.2f} V, PA1 pk {r['vauxs_pk']:.2f} V, +3V3 {r['p3v3_min']:.2f}..{r['p3v3_max']:.2f} V")

    print("\n=== sim 3: VBAT divider")
    dv = sim_divider(plots, ld)
    print(f"  gain {dv['gain']:.5f} (ideal 1/11 = {1/11:.5f}); tau-63% {dv['t_63']*1e3:.2f} ms, 0.5 LSB settle {dv['t_settle']*1e3:.1f} ms")
    for v, (a_, code) in dv["points"].items():
        print(f"  VBAT {v:5.1f} V -> PA0 {a_:.3f} V, code {code}")
    for tag in ("ldA_slow", "ldA_lamp", "ldB_slow", "ldB_relay"):
        vb, vs, va = dv["ld"][tag]
        print(f"  load dump {tag}: VBATF pk {vb:.1f} V -> PA0 pk {vs:.2f} V; AUX_IN on bus -> PA1 pk {va:.2f} V "
              f"(VDD+0.3 = {LIM['vdd']+0.3:.1f}, FT op max {LIM['ft_op']}, FT abs max {LIM['ft_abs']:.1f})")

    print("\n=== sim 4: LDO start-up / dips")
    st = sim_startup(plots)
    for r in st:
        print(f"  [{r['tag']}] {r['desc']}: VIN pk {r['vin_pk']:.1f} V, VBATF pk {r['vbatf_pk']:.1f} V, VBUS pk {r['vbus_pk']:.2f} V, "
              f"inrush {r['i_in_pk']:.2f} A (D1 {r['id1_pk']:.2f} A); +3V3 10-90% {fmt(r['t_rise'] and r['t_rise']*1e6, ' us', 0)}, "
              f"to 3.0 V {fmt(r['t_30'] and r['t_30']*1e6, ' us', 0)}, max {r['vo_max']:.3f} V, min {r['vo_min']:.3f} V, VIN min {r['vin_min']:.2f} V "
              f"(datasheet-dropout worst {r['vo_min_ds']:.2f} V)")
    if plots:
        print(f"\nplots: {OUT}/sim*.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
