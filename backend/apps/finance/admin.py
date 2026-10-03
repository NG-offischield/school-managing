"""Django admin registrations — developer tooling only.

Money never moves through the admin: payments, ledgers, allocations and
refunds are read-only here (and append-only in PostgreSQL); use the services.
"""

from django.contrib import admin

from .models import (
    FeeSchedule,
    FeeType,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentAllocation,
    PaymentRefund,
    SimulationTreasury,
    TreasuryTransaction,
    Wallet,
    WalletTransaction,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


for model in (
    Payment,
    PaymentAllocation,
    PaymentRefund,
    WalletTransaction,
    TreasuryTransaction,
    SimulationTreasury,
    Wallet,
    Invoice,
    InvoiceLine,
):
    admin.site.register(model, ReadOnlyAdmin)

for model in (FeeType, FeeSchedule):
    admin.site.register(model)
