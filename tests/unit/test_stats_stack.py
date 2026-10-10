"""The statistics libraries (docs/kb/decisions/adr-016-statistics-libraries.md)
install together with pandas and give the answers the models will rely on."""

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats


def test_scipy_probability():
    assert round(stats.norm.cdf(1.96), 3) == 0.975  # chance of a normal value under 1.96 standard deviations


def test_statsmodels_regression_on_a_pandas_frame():
    frame = pd.DataFrame({"x": np.arange(20.0)})
    frame["y"] = 3 * frame["x"] + 2
    fit = sm.OLS(frame["y"], sm.add_constant(frame["x"])).fit()
    assert round(fit.params["x"], 6) == 3 and round(fit.params["const"], 6) == 2
