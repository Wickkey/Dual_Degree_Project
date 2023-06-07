import numpy as np
from scipy.integrate import odeint
from functools import partial
from extents import compute_matrices
from datatools import DataTools
from ratelawgen import RateLaw


class Simulate(DataTools):
    def __init__(
        self, N, Mw, V, Winhat=None, uin=None, uout=None, n0=None, config=None
    ):
        """
        Initializes a new instance of the Simulate class.

        Args:
            N (array-like): The stoichiometric list.
            Mw (array-like): The molecular weight data.
            V (array-like): The volume data.
            Winhat (array-like, optional): The input stoichiometric matrix. Defaults to None.
            uin (array-like, optional): The input concentration data. Defaults to None.
            uout (array-like, optional): The output concentration data. Defaults to None.
            n0 (array-like, optional): The initial concentration data. Defaults to None.
            config (dict, optional): The reactor configuration data. Defaults to None.

        Raises:
            ValueError: If n0 is None.

        """
        if n0 is None:
            raise ValueError("n0 cannot be None")

        self.add_stoichiometry_data(N)

        self.add_molweight_data(Mw)
        if self.Mw.shape[0] != self.S:
            raise ValueError(
                f"Dimension of Mw {self.Mw.shape} should be {self.S}x{self.S} and \
                    is not consistent with Stoichiometric Matrix N {self.N.shape}"
            )

        V, Winhat, uin, uout = self.add_reactor_config(V, Winhat, uin, uout, config)
        self.add_volume_data(V, kind="linear")

        self.add_Winhat_data(Winhat)
        if self.Winhat.shape[0] != self.S:
            raise ValueError(
                f"Dimension of Winhat {self.Winhat.shape} should be {self.S}x{self.P} \
                    and is not consistent with Stoichiometric Matrix N {self.N.shape}"
            )

        self.add_uin_data(uin, kind="linear")
        if self.uin(0).shape[0] != self.P:
            raise ValueError(
                f"Dimension of uin {self.uin.shape} is not consistent with Winhat {self.Win.shape}"
            )

        self.add_uout_data(uout, kind="linear")
        self.add_n0_data(n0)
        if self.n0.shape[0] != self.S:
            raise ValueError(
                f"Required {self.S} species for n0. Received {self.n0.shape[0]} species instead"
            )

        self.Win = np.linalg.pinv(self.Mw) @ self.Winhat  # (SxP) matrix
        if len(self.Win.shape) == 1:
            self.Win = np.reshape(self.Win, (self.Win.shape[0], 1))
        self.m0 = np.sum(self.Mw @ self.n0)

    def add_ratelaws(self, ratelaws, K):
        """
        Adds rate laws and associated rate constants.

        Args:
            ratelaws (list): The list of rate law functions.
            K (array-like): The rate constant values.

        """
        self.ratelaws = [
            partial(ratelaw.function, K=K[idx])
            if isinstance(ratelaw, RateLaw)
            else partial(ratelaw, K=K[idx])
            for idx, ratelaw in enumerate(ratelaws)
        ]

    def mole_balance(self, y, t):
        """
        Computes the mole balance equations.

        Args:
            y (array-like): The concentration vector.
            t (float): The current time.

        Returns:
            array-like: The derivative of the concentration vector.

        """
        c = y / self.V(t)
        rate = np.array([ratelaw(c) for ratelaw in self.ratelaws])
        m = np.sum(self.Mw @ y)  # current mass
        dydt = (
            (self.N.T @ rate * self.V(t))
            + (self.Win @ self.uin(t))
            - (self.uout(t) * y / m)
        )
        return dydt

    def run_simulation(self, time, alpha=0):
        """
        Runs the simulation.

        Args:
            time (array-like): The time points for the simulation.
            alpha (float, optional): The noise level for the simulation. Defaults to 0.

        Returns:
            dict: A dictionary containing the simulation results.

        """

        self.time = time
        sol = odeint(self.mole_balance, self.n0, time)

        nSamples, nSpecies = sol.shape[0], sol.shape[1]
        noise_mean = np.zeros(nSpecies)
        noise_std = (alpha / 100) * np.diag(np.ndarray.max(sol, axis=0))
        noise_cov = noise_std**2
        noise = np.random.multivariate_normal(
            mean=noise_mean, cov=noise_cov, size=nSamples
        )

        self._sol = sol + noise

        self._reaction_rate = np.array(
            [ratelaw(self._sol.T / self.V(time)) for ratelaw in self.ratelaws]
        )  # check this equation for vector of V

        self._flow_rate = ((self.N.T) @ self._reaction_rate * self.V(time)).T

        self._reaction_rate = self._reaction_rate.T

        q0T, S0T, M0T, Q0T = compute_matrices(self.N, self.Win, self.n0)

        self._xr = self._sol @ S0T.T

        self._xin = self._sol @ M0T.T

        self._lamda = self._sol @ q0T.T

        d = {
            "moles": self._sol,
            "reaction_rate": self._reaction_rate,
            "flow_rate": self._flow_rate,
            "xr": self._xr,
            "xin": self._xin,
            "xout": 1 - self._lamda,
        }

        return d
