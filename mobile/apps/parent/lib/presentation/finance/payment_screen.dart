import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../../data/parent_repository.dart';
import '../../data/payment_flow.dart';
import '../../models/models.dart';
import '../common.dart';
import 'receipt.dart';

/// Facture -> détail -> droit de payer (réponse du serveur) -> confirmation
/// -> paiement -> résultat du SERVEUR -> reçu.
///
/// The amount is the invoice's balance_due exactly as the server gives it:
/// it is shown, never typed nor recomputed. Pops `true` when a payment was
/// answered, so the finance screen reloads.
class PaymentScreen extends StatefulWidget {
  const PaymentScreen({super.key, required this.child, required this.invoiceId});

  final Child child;
  final String invoiceId;

  @override
  State<PaymentScreen> createState() => _PaymentScreenState();
}

class _Ready {
  _Ready(this.obligations, this.invoice, this.wallets);

  final Obligations obligations;
  final Invoice invoice;
  final List<Wallet> wallets;
}

class _PaymentScreenState extends State<PaymentScreen> {
  Future<_Ready>? _future;
  PaymentFlow? _flow;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _flow?.dispose();
    super.dispose();
  }

  Future<_Ready> _fetch() async {
    final repo = context.read<ParentRepository>();
    // Asked again now: the right to pay and the balance are the server's, at this moment.
    final obligations = await repo.obligations(widget.child.id);
    final invoice = await repo.invoice(widget.invoiceId);
    final wallets = obligations.canPay && invoice.payable ? await repo.wallets() : const <Wallet>[];
    _flow?.dispose();
    _flow = PaymentFlow(repo, childId: widget.child.id, invoice: invoice)..addListener(_changed);
    final usable = wallets.where((w) => w.active).toList();
    if (usable.length == 1) _flow!.chooseWallet(usable.single);
    return _Ready(obligations, invoice, wallets);
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  void _load() => setState(() {
    _future = _fetch()..ignore();
  });

  Future<void> _confirmAndPay(Invoice invoice) async {
    final flow = _flow!;
    final wallet = flow.wallet;
    if (wallet == null || flow.state == PayState.paying) return;
    final amount = formatMoney(invoice.balance, invoice.currency);
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Confirmer le paiement'),
        content: Text(
          '$amount seront débités du portefeuille ${wallet.label} pour ${widget.child.name} '
          '(facture ${invoice.number}).',
        ),
        actions: [
          TextButton(
            key: const Key('pay.cancel'),
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Annuler'),
          ),
          FilledButton(
            key: const Key('pay.confirm'),
            onPressed: () => Navigator.of(context).pop(true),
            child: Text('Payer $amount'),
          ),
        ],
      ),
    );
    if (ok == true) await flow.pay();
  }

  @override
  Widget build(BuildContext context) {
    final flow = _flow;
    final paying = flow?.state == PayState.paying;
    final answered = flow?.state == PayState.done;
    return PopScope(
      canPop: !paying, // never leave while the debit is being decided
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Payer une facture'),
          leading: BackButton(onPressed: paying ? null : () => Navigator.of(context).pop(answered)),
        ),
        body: AsyncBody<_Ready>(future: _future, onRetry: _load, builder: (context, data) => _body(data)),
      ),
    );
  }

  Widget _body(_Ready data) {
    final flow = _flow!;
    final invoice = data.invoice;
    final amount = formatMoney(invoice.balance, invoice.currency);
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(widget.child.name, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
                const SizedBox(height: 6),
                InfoRow('Facture', invoice.number),
                if (invoice.reason.isNotEmpty) InfoRow('Motif', invoice.reason),
                InfoRow('Échéance', invoice.dueDate == null ? '—' : dateOnly.format(invoice.dueDate!)),
                InfoRow('Total', formatMoney(invoice.total, invoice.currency)),
                InfoRow('Déjà payé', formatMoney(invoice.paid, invoice.currency)),
                const SizedBox(height: 6),
                StatusChip(invoice.statusLabel, tone: invoice.payable ? Tone.info : Tone.success),
                const Divider(height: 24),
                Row(
                  children: [
                    const Expanded(
                      child: Text('Montant à payer', style: TextStyle(fontWeight: FontWeight.w600)),
                    ),
                    Text(
                      amount,
                      key: const Key('pay.amount'),
                      style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
        ..._action(data, flow, amount),
      ],
    );
  }

  List<Widget> _action(_Ready data, PaymentFlow flow, String amount) {
    final invoice = data.invoice;
    if (!data.obligations.canPay) {
      return const [
        SizedBox(height: 12),
        MessageBanner(
          'L\'établissement ne vous a pas autorisé(e) à payer pour cet enfant. Vous pouvez consulter la facture.',
          tone: Tone.info,
        ),
      ];
    }
    if (flow.state == PayState.done) return _result(flow.payment!, flow);
    if (!invoice.payable) {
      return const [SizedBox(height: 12), MessageBanner('Cette facture est déjà réglée.', tone: Tone.success)];
    }
    final usable = data.wallets.where((w) => w.active).toList();
    return [
      const SectionTitle('Payer avec'),
      if (data.wallets.isEmpty)
        const MessageBanner(
          'Aucun portefeuille mobile à votre nom. L\'établissement doit d\'abord vous en ouvrir un.',
          tone: Tone.info,
        ),
      RadioGroup<String>(
        groupValue: flow.wallet?.id,
        onChanged: (id) => flow.chooseWallet(data.wallets.firstWhere((w) => w.id == id)),
        child: Column(
          children: [
            for (final w in data.wallets)
              Card(
                child: RadioListTile<String>(
                  key: Key('wallet.${w.id}'),
                  value: w.id,
                  // A blocked wallet is shown, not offered; none can change while a payment is unresolved.
                  enabled: w.active && !flow.walletLocked && flow.state != PayState.paying,
                  title: Text(w.label),
                  subtitle: Text(w.active ? 'Solde : ${formatMoney(w.balance, w.currency)}' : 'Portefeuille bloqué'),
                ),
              ),
          ],
        ),
      ),
      if (flow.state == PayState.unknown)
        const Padding(
          padding: EdgeInsets.only(top: 12),
          child: MessageBanner(
            'La réponse du serveur n\'est pas arrivée : le paiement a peut-être été enregistré. « Réessayer » '
            'renvoie la MÊME demande : il n\'y aura jamais de second débit.',
            tone: Tone.warning,
          ),
        ),
      if (flow.state == PayState.refused && flow.error != null)
        Padding(padding: const EdgeInsets.only(top: 12), child: MessageBanner(flow.error!.userMessage)),
      const SizedBox(height: 16),
      if (flow.state == PayState.paying)
        const FilledButton(
          key: Key('pay.busy'),
          onPressed: null,
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2.5)),
              SizedBox(width: 12),
              Text('Paiement en cours…'),
            ],
          ),
        )
      else if (flow.state == PayState.unknown)
        FilledButton.icon(
          key: const Key('pay.retry'),
          onPressed: flow.pay, // same intent, same key
          icon: const Icon(Icons.refresh),
          label: const Text('Réessayer'),
        )
      else if (flow.state == PayState.refused && flow.error is ConflictException)
        OutlinedButton.icon(
          key: const Key('pay.reload'),
          onPressed: _load, // the balance or the status changed: read them again
          icon: const Icon(Icons.refresh),
          label: const Text('Recharger la facture'),
        )
      else
        FilledButton.icon(
          key: const Key('pay.submit'),
          onPressed: flow.wallet == null || usable.isEmpty ? null : () => _confirmAndPay(invoice),
          icon: const Icon(Icons.lock_outline),
          label: Text('Payer $amount'),
        ),
    ];
  }

  List<Widget> _result(Payment payment, PaymentFlow flow) {
    final ok = payment.succeeded;
    return [
      const SizedBox(height: 12),
      Card(
        key: const Key('pay.result'),
        color: ok ? Tokens.successBg : Tokens.errorBg,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(ok ? Icons.check_circle : Icons.cancel, color: ok ? Tokens.success : Tokens.error, size: 30),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(payment.outcome, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              InfoRow('Référence', payment.reference, strong: true),
              InfoRow('Montant', formatMoney(payment.amount, payment.currency)),
              if (payment.at != null) InfoRow('Date', dateTime.format(payment.at!)),
              if (payment.failureReason != null) InfoRow('Motif du refus', payment.failureReason!),
              if (payment.replayed)
                Padding(
                  padding: EdgeInsets.only(top: 6),
                  child: Text(
                    'Ce paiement avait déjà été enregistré : aucun second débit.',
                    style: TextStyle(color: Tokens.textSecondary),
                  ),
                ),
            ],
          ),
        ),
      ),
      const SizedBox(height: 12),
      if (payment.hasReceipt)
        FilledButton.icon(
          key: const Key('pay.receipt'),
          onPressed: () => downloadReceipt(context, payment),
          icon: const Icon(Icons.receipt_long_outlined),
          label: const Text('Télécharger le reçu'),
        )
      else
        FilledButton.icon(
          key: const Key('pay.again'),
          onPressed: flow.startOver, // a NEW payment (new key)
          icon: const Icon(Icons.refresh),
          label: const Text('Réessayer'),
        ),
      const SizedBox(height: 8),
      OutlinedButton(
        key: const Key('pay.close'),
        onPressed: () => Navigator.of(context).pop(true),
        child: const Text('Retour à la scolarité'),
      ),
    ];
  }
}
