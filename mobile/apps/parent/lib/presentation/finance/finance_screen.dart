import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../../data/parent_repository.dart';
import '../../data/pdf_store.dart';
import '../../models/models.dart';
import '../common.dart';

/// Scolarité et paiements of the selected child. The SERVER decides:
/// - without `can_view_financial_data`, obligations and invoices are not
///   even requested (the server would answer 403); only my own payments
///   (as payer) are listed;
/// - "can pay" is the server's answer for THIS account, never deduced from
///   the fact that the parent sees the child;
/// - every amount comes from the server (strings, never recomputed).
/// No payment is initiated from this screen.
class FinanceScreen extends StatelessWidget {
  const FinanceScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Scolarité et paiements'), actions: const [ChildSwitcher()]),
      body: ChildBody(
        builder: (context, child) => _ChildFinance(key: ValueKey(child.id), child: child),
      ),
    );
  }
}

class _Data {
  _Data(this.obligations, this.invoices, this.payments);

  final Obligations? obligations;
  final List<Invoice> invoices;
  final List<Payment> payments;
}

Tone invoiceTone(String status) => switch (status) {
  'PAID' => Tone.success,
  'PARTIALLY_PAID' => Tone.warning,
  'ISSUED' => Tone.info,
  _ => Tone.neutral,
};

Tone paymentTone(String status) => switch (status) {
  'SUCCEEDED' => Tone.success,
  'PENDING' => Tone.info,
  'REFUNDED' || 'PARTIALLY_REFUNDED' => Tone.warning,
  _ => Tone.danger,
};

class _ChildFinance extends StatefulWidget {
  const _ChildFinance({super.key, required this.child});

  final Child child;

  @override
  State<_ChildFinance> createState() => _ChildFinanceState();
}

class _ChildFinanceState extends State<_ChildFinance> {
  Future<_Data>? _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<_Data> _fetch() async {
    final repo = context.read<ParentRepository>();
    final id = widget.child.id;
    if (!widget.child.canViewFinance) return _Data(null, const [], await repo.payments(id));
    final obligations = await repo.obligations(id);
    final invoices = await repo.invoices(id);
    final payments = await repo.payments(id);
    return _Data(obligations, invoices, payments);
  }

  void _load() => setState(() {
    _future = _fetch()..ignore();
  });

  Future<void> _receipt(Payment payment) async {
    final repo = context.read<ParentRepository>();
    final store = context.read<PdfStore>();
    try {
      final bytes = await repo.receiptPdf(payment.id);
      await store.save('recu-${payment.reference}.pdf', bytes);
      if (mounted) showMessage(context, 'Reçu ${payment.reference} enregistré dans l\'application.');
    } on ApiException catch (error) {
      if (mounted) showMessage(context, error.userMessage);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AsyncBody<_Data>(
      future: _future,
      onRetry: _load,
      builder: (context, data) => RefreshIndicator(
        onRefresh: () async {
          _load();
          await _future?.catchError((_) => _Data(null, const [], const []));
        },
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
          children: [
            Text(widget.child.name, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
            if (data.obligations == null)
              const Padding(
                padding: EdgeInsets.only(top: 12),
                child: MessageBanner(
                  'L\'établissement ne vous a pas donné accès à la situation financière de cet enfant. '
                  'Seuls vos propres paiements sont affichés.',
                  tone: Tone.info,
                ),
              )
            else
              ..._obligations(data.obligations!, data.invoices),
            const SectionTitle('Historique des paiements'),
            if (data.payments.isEmpty)
              const Padding(
                padding: EdgeInsets.all(8),
                child: Text('Aucun paiement.', style: TextStyle(color: Tokens.textSecondary)),
              ),
            for (final p in data.payments)
              Card(
                child: ListTile(
                  title: Text(formatMoney(p.amount, p.currency), style: const TextStyle(fontWeight: FontWeight.w700)),
                  subtitle: Text('${p.reference}${p.at == null ? '' : ' · ${dateTime.format(p.at!)}'}'),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      StatusChip(p.statusLabel, tone: paymentTone(p.status)),
                      if (p.hasReceipt)
                        IconButton(
                          key: Key('receipt.${p.id}'),
                          tooltip: 'Télécharger le reçu',
                          icon: const Icon(Icons.download_outlined),
                          onPressed: () => _receipt(p),
                        ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  List<Widget> _obligations(Obligations o, List<Invoice> invoices) => [
    const SectionTitle('Situation'),
    Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            InfoRow('Reste à payer', formatMoney(o.balanceDue, o.currency), strong: true),
            InfoRow('Échéances', o.solvencyLabel),
            const SizedBox(height: 8),
            StatusChip(
              o.canPay ? 'Vous pouvez payer pour cet enfant' : 'Paiement non autorisé pour votre compte',
              tone: o.canPay ? Tone.success : Tone.neutral,
            ),
          ],
        ),
      ),
    ),
    const SectionTitle('Factures'),
    if (invoices.isEmpty)
      const Padding(
        padding: EdgeInsets.all(8),
        child: Text('Aucune facture.', style: TextStyle(color: Tokens.textSecondary)),
      ),
    for (final i in invoices)
      Card(
        child: ExpansionTile(
          title: Text(i.number, style: const TextStyle(fontWeight: FontWeight.w700)),
          subtitle: Text(
            'Échéance ${i.dueDate == null ? '—' : dateOnly.format(i.dueDate!)} · reste ${formatMoney(i.balance, i.currency)}',
          ),
          trailing: StatusChip(i.statusLabel, tone: invoiceTone(i.status)),
          childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
          children: [
            for (final line in i.lines) InfoRow(line.label, formatMoney(line.total, i.currency)),
            const Divider(),
            InfoRow('Total', formatMoney(i.total, i.currency), strong: true),
            InfoRow('Payé', formatMoney(i.paid, i.currency)),
          ],
        ),
      ),
  ];
}
