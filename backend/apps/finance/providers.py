"""Payment providers (ADR 0013).

The finance services only talk to this interface: a provider charges and
returns a ProviderResult. Adding a real mobile-money provider (Orange Money,
MTN MoMo...) = one new class registered in PROVIDERS; Payment, ledgers,
invoices and the API stay unchanged.

`moves_simulated_wallet`: with the SIMULATION provider the money lives in our
own Wallet table, so the service debits it; a real provider keeps the payer's
money on its side and only the treasury is credited.
"""

import secrets
from dataclasses import dataclass

from .models import AccountStatus, PaymentMethod, PaymentStatus, SimulationBehavior


@dataclass(frozen=True)
class ProviderResult:
    status: str  # a PaymentStatus value
    provider_reference: str | None = None
    message: str | None = None


class SimulationWalletProvider:
    """Deterministic fake mobile-money provider.

    Outcome, in this order:
    blocked wallet -> DECLINED; wallet.simulation_behavior DECLINE / TIMEOUT /
    PROVIDER_ERROR -> that outcome; balance < amount -> INSUFFICIENT_FUNDS;
    otherwise SUCCEEDED. Same inputs, same result: fully testable.
    """

    code = "SIMULATION_WALLET"
    moves_simulated_wallet = True

    def charge(self, *, wallet, amount, reference):
        if wallet.status == AccountStatus.BLOCKED:
            return ProviderResult(PaymentStatus.DECLINED, message="Wallet blocked.")
        behavior = wallet.simulation_behavior
        if behavior == SimulationBehavior.DECLINE:
            return ProviderResult(PaymentStatus.DECLINED, message="Declined by the provider.")
        if behavior == SimulationBehavior.TIMEOUT:
            return ProviderResult(PaymentStatus.TIMEOUT, message="The provider did not answer in time.")
        if behavior == SimulationBehavior.PROVIDER_ERROR:
            return ProviderResult(PaymentStatus.PROVIDER_ERROR, message="Provider internal error.")
        if wallet.balance < amount:
            return ProviderResult(PaymentStatus.INSUFFICIENT_FUNDS, message="Insufficient funds.")
        return ProviderResult(PaymentStatus.SUCCEEDED, provider_reference=f"SIM-{secrets.token_hex(8).upper()}")


class CashProvider:
    """Cash received at the school desk by an administrator."""

    code = "CASH"
    moves_simulated_wallet = False

    def charge(self, *, wallet, amount, reference):
        return ProviderResult(PaymentStatus.SUCCEEDED, provider_reference=f"CASH-{reference}")


PROVIDERS = {
    PaymentMethod.WALLET: SimulationWalletProvider(),
    PaymentMethod.CASH: CashProvider(),
}


def provider_for(method):
    return PROVIDERS[method]
