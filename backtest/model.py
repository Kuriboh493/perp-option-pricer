"""NumPy port of the pricing core in ../index.html (Heston stochastic volatility with Merton jumps)."""
import numpy as np
from scipy.special import ndtr

NGRID = 512


def black(f, K, v, cp):
    """Undiscounted Black price on a forward; v is total variance, cp is +1 call / -1 put."""
    f, K, v, cp = np.broadcast_arrays(np.asarray(f, float), np.asarray(K, float), np.asarray(v, float), np.asarray(cp, float))
    s = np.sqrt(np.maximum(v, 1e-14))
    d1 = (np.log(f / K) + v / 2) / s
    return np.where(v > 1e-14, cp * (f * ndtr(cp * d1) - K * ndtr(cp * (d1 - s))), np.maximum(cp * (f - K), 0))


def implied_vol(price, f, K, T, cp):
    """Black vol reproducing an undiscounted price (vectorised bisection)."""
    price, f, K, T, cp = np.broadcast_arrays(*[np.asarray(a, float) for a in (price, f, K, T, cp)])
    lo, hi = np.full(price.shape, 1e-4), np.full(price.shape, 8.0)
    for _ in range(50):
        mid = (lo + hi) / 2
        below = black(f, K, mid * mid * T, cp) < price
        lo, hi = np.where(below, mid, lo), np.where(below, hi, mid)
    iv = (lo + hi) / 2
    return np.where((price <= np.maximum(cp * (f - K), 0) + 1e-12) | (iv > 7.9), np.nan, iv)


def log_cf(u, tau, T, m):
    """Log characteristic function of ln(F_T / forward). Variance runs on vol-clock time tau, jumps on calendar time T."""
    out = np.zeros_like(u, dtype=complex)
    if tau > 0:
        sv, s2 = m["sv"], m["sv"] ** 2
        xi = m["kv"] - m["rho"] * sv * 1j * u
        d = np.sqrt(xi * xi + s2 * (u * u + 1j * u))
        g = (xi - d) / (xi + d)
        e = np.exp(-d * tau)
        out += m["kv"] * m["th"] / s2 * ((xi - d) * tau - 2 * np.log((1 - g * e) / (1 - g))) + (xi - d) / s2 * (1 - e) / (1 - g * e) * m["v0"]
    if m["lam"] > 0 and T > 0:
        k = np.exp(m["muJ"] + m["dJ"] ** 2 / 2) - 1
        out += m["lam"] * T * (np.exp(1j * u * m["muJ"] - m["dJ"] ** 2 * u * u / 2) - 1 - 1j * u * k)
    return out


def cf_grid(tau, T, m):
    """Simpson-weighted samples of phi(u - i/2)/(u^2 + 1/4) on u = sinh(t)/2, reusable across strikes."""
    m = dict(m, sv=max(0.01, m["sv"]), rho=min(0.99, max(-0.99, m["rho"])))
    U = 16.0
    while U < 20000 and np.exp(log_cf(np.array([U - 0.5j]), tau, T, m).real[0]) / (U * U + 0.25) > 1e-10:
        U *= 1.5
    t = np.linspace(0, np.arcsinh(2 * U), NGRID + 1)
    w = np.full(NGRID + 1, 2.0); w[1::2] = 4.0; w[0] = w[-1] = 1.0
    us = np.sinh(t) / 2
    return us, np.exp(log_cf(us - 0.5j, tau, T, m)) * 2 / np.cosh(t) * w * (t[1] - t[0]) / 3


def bates(fwd, K, cp, tau, T, m, grid=None):
    """Undiscounted option prices on forward(s) fwd for strikes K (Lewis 2001 single integral)."""
    fwd, K, cp = np.broadcast_arrays(np.asarray(fwd, float), np.asarray(K, float), np.asarray(cp, float))
    if not (tau > 0 or (m["lam"] > 0 and T > 0)):
        return np.maximum(cp * (fwd - K), 0)
    us, w = grid if grid is not None else cf_grid(tau, T, m)
    k = np.log(fwd / K)
    I = (np.exp(1j * np.multiply.outer(k, us)) * w).real.sum(-1)
    C = np.minimum(fwd, np.maximum(np.maximum(fwd - np.sqrt(fwd * K) / np.pi * I, fwd - K), 0))
    return np.where(cp > 0, C, C - fwd + K)


def fair_perp(S, r, q, iota, funding_hours):
    kap = 8760 / funding_hours
    return S * (kap - iota) / (kap - (r - q))


BTC_PRESET = dict(kv=3.0, sv=1.5, rho=-0.1, lam=8.0, muJ=-0.03, dJ=0.07)

if __name__ == "__main__":
    # same checks as the JavaScript core
    m = dict(v0=0.010201, th=0.019, kv=6.21, sv=0.61, rho=-0.7, lam=0, muJ=0, dJ=0)
    print("Broadie-Kaya 6.8061 ->", np.exp(-0.0319) * bates(100 * np.exp(0.0319), 100, 1, 1, 1, m))
    F, T = fair_perp(100000, 0.04, 0, 0.1095, 8), 30 / 365
    m = dict(BTC_PRESET, v0=0.25, th=0.55 ** 2)
    print("JS BTC preset 4164.71754 ->", np.exp(-0.04 * T) * bates(F * np.exp(0.04 * T), 105000, 1, T, T, m))
