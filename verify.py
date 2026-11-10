"""Independent checks of the calculation logic. Run:  python verify.py"""
import math

from app import cost_of_capital

# ---- Hand calculation (done independently, step by step) -------------------
# beta_u=1.20, t=25%, d=30%, ERP=6.5%, y_us=4.5%, y_for=9.0%, BBB spread=1.11%
#   D/E = 0.3/0.7 = 0.428571 ; beta_L = 1.2*(1+0.75*0.428571) = 1.585714
#   Ke_USD = 4.5% + 1.585714*6.5% = 14.80714%
#   Kd_USD = 4.5% + 1.11% = 5.61% ; after tax = 4.2075%
#   WACC_USD = 0.7*14.80714% + 0.3*4.2075% = 11.62725%
#   factor = 1.09/1.045 = 1.043062
#   Ke_for = 1.1480714*1.043062 - 1 = 19.75..% ; Kd_for = 1.0561*1.043062-1 = 10.1578..%
r = cost_of_capital(1.20, 0.25, 0.0111, 0.045, 0.09, 0.065, 0.30)
fac = 1.09 / 1.045
assert math.isclose(r["beta_levered"], 1.2 * (1 + 0.75 * 0.3 / 0.7))
assert math.isclose(r["usd"]["ke"], 0.045 + 1.585714285714 * 0.065, rel_tol=1e-9)
assert math.isclose(r["usd"]["wacc"], 0.7 * 0.1480714285714 + 0.3 * 0.0561 * 0.75, rel_tol=1e-9)
assert math.isclose(r["for"]["ke"], 1.1480714285714 * fac - 1, rel_tol=1e-9)
assert math.isclose(r["for"]["kd"], 1.0561 * fac - 1, rel_tol=1e-9)
assert math.isclose(r["for"]["wacc"], 0.7 * (1.1480714285714 * fac - 1) + 0.3 * (1.0561 * fac - 1) * 0.75,
                    rel_tol=1e-9)
print("hand example OK  WACC_USD=%.4f%%  WACC_for=%.4f%%" % (100 * r["usd"]["wacc"], 100 * r["for"]["wacc"]))

# ---- Check 1: equal government yields -> equal results ---------------------
r = cost_of_capital(1.0, 0.21, 0.0111, 0.045, 0.045, 0.065, 0.30)
for k in ("ke", "kd", "wacc"):
    assert math.isclose(r["usd"][k], r["for"][k], abs_tol=1e-12), k
print("check 1 OK: equal yields -> identical USD and foreign results")

# ---- Check 2: zero debt -> WACC == cost of equity --------------------------
r = cost_of_capital(1.0, 0.21, 0.0111, 0.045, 0.09, 0.065, 0.0)
assert math.isclose(r["usd"]["wacc"], r["usd"]["ke"]) and math.isclose(r["for"]["wacc"], r["for"]["ke"])
print("check 2 OK: zero debt -> WACC = cost of equity (both currencies)")

# ---- Check 3: foreign spread override leaves USD results unchanged ---------
a = cost_of_capital(1.0, 0.21, 0.0111, 0.045, 0.09, 0.065, 0.30)
b = cost_of_capital(1.0, 0.21, 0.0111, 0.045, 0.09, 0.065, 0.30, spread_for_override=0.05)
assert a["usd"] == b["usd"] and a["for"]["ke"] == b["for"]["ke"]
assert a["for"]["wacc"] != b["for"]["wacc"]
# override equal to the automatic spread reproduces the automatic result
c = cost_of_capital(1.0, 0.21, 0.0111, 0.045, 0.09, 0.065, 0.30, spread_for_override=a["for"]["spread_auto"])
assert math.isclose(a["for"]["wacc"], c["for"]["wacc"])
print("check 3 OK: spread override changes only foreign WACC; USD unchanged")
print("ALL CHECKS PASSED")
