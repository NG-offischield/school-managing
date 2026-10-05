/// Parent mobile payment (ADR 0013 on the client side): the server decides
/// the right to pay, the amount (balance_due), the outcome and the receipt;
/// the phone shows them, confirms before the debit, and never pays twice for
/// one intent (idempotency key kept until a definitive answer).
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:school_core/school_core.dart';
import 'package:school_parent/data/payment_flow.dart';
import 'package:school_parent/models/models.dart';

import 'app_test.dart' show Harness, caught, nbsp;
import 'fake_api.dart';

void main() {
  setUpAll(() => initializeDateFormatting('fr_FR'));

  Iterable<Map<String, dynamic>> paymentPosts(Harness h) => h.fake.requests
      .where((r) => r.method == 'POST' && r.url.path.endsWith('finance/payments/'))
      .map((r) => (jsonDecode(r.body) as Map).cast<String, dynamic>());

  Future<Harness> signedIn(WidgetTester tester, FakePerson Function(FakeApi) who) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, who(h.fake));
    return h;
  }

  /// Paul (can_pay on Zoé) -> Finance -> the invoice -> « Payer ».
  Future<Harness> openPayment(WidgetTester tester) async {
    final h = await signedIn(tester, (f) => f.b);
    await h.tab(tester, 'Finance');
    await tester.tap(find.text('FAC-2026-0003'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('invoice.pay.inv3')));
    await tester.pumpAndSettle();
    return h;
  }

  Future<void> confirmPayment(WidgetTester tester) async {
    await tester.ensureVisible(find.byKey(const Key('pay.submit')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('pay.submit')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('pay.confirm')));
    await tester.pumpAndSettle();
  }

  group('services (PaymentFlow + repository)', () {
    testWidgets('success: the amount sent is the server\'s balance, one payment, wallet debited', (tester) async {
      final h = await signedIn(tester, (f) => f.b);
      final invoice = await h.repository.invoice('inv3');
      final wallet = (await h.repository.wallets()).first;
      final flow = PaymentFlow(h.repository, childId: 'c3', invoice: invoice)..chooseWallet(wallet);
      await flow.pay();
      expect(flow.state, PayState.done);
      expect(flow.payment!.succeeded, isTrue);
      final sent = paymentPosts(h).single;
      expect(sent['amount'], '40000.00'); // exactly the balance_due string of the server
      expect(sent['payment_method'], 'WALLET');
      expect(sent['invoices'], ['inv3']);
      expect('${sent['idempotency_key']}', startsWith('mob-'));
      expect(h.fake.created, 1);
      expect((await h.repository.invoice('inv3')).status, 'PAID');
      expect((await h.repository.wallets()).first.balance, '60000.00');
    });

    testWidgets('double tap / double submission: a single request', (tester) async {
      final h = await signedIn(tester, (f) => f.b);
      final flow = PaymentFlow(h.repository, childId: 'c3', invoice: await h.repository.invoice('inv3'))
        ..chooseWallet((await h.repository.wallets()).first);
      h.fake.holdPayment = Completer<void>();
      final first = flow.pay();
      final second = flow.pay(); // while the first is running
      expect(flow.state, PayState.paying);
      h.fake.holdPayment!.complete();
      await Future.wait([first, second]);
      expect(paymentPosts(h), hasLength(1));
      expect(h.fake.created, 1);
    });

    testWidgets('answer lost after the debit: retry = same key, the server replays, no second debit', (tester) async {
      final h = await signedIn(tester, (f) => f.b);
      final flow = PaymentFlow(h.repository, childId: 'c3', invoice: await h.repository.invoice('inv3'))
        ..chooseWallet((await h.repository.wallets()).first);
      h.fake.loseNextAnswer = true;
      await flow.pay();
      expect(flow.state, PayState.unknown);
      expect(flow.error, isA<NetworkException>());
      expect(flow.walletLocked, isTrue);
      await flow.pay(); // « Réessayer »
      expect(flow.state, PayState.done);
      expect(flow.payment!.replayed, isTrue);
      expect(h.fake.created, 1);
      final keys = paymentPosts(h).map((p) => p['idempotency_key']).toSet();
      expect(keys, hasLength(1));
      expect((await h.repository.wallets()).first.balance, '60000.00'); // debited once
    });

    testWidgets('network down before the server: retry with the same key creates one payment', (tester) async {
      final h = await signedIn(tester, (f) => f.b);
      final flow = PaymentFlow(h.repository, childId: 'c3', invoice: await h.repository.invoice('inv3'))
        ..chooseWallet((await h.repository.wallets()).first);
      h.fake.offline = true;
      await flow.pay();
      expect(flow.state, PayState.unknown);
      h.fake.offline = false;
      await flow.pay();
      expect(flow.payment!.succeeded, isTrue);
      expect(h.fake.created, 1);
      expect(paymentPosts(h).map((p) => p['idempotency_key']).toSet(), hasLength(1));
    });

    testWidgets('recorded failure (insufficient funds): definitive; a new attempt is a NEW key', (tester) async {
      final h = await signedIn(tester, (f) => f.b);
      final flow = PaymentFlow(h.repository, childId: 'c3', invoice: await h.repository.invoice('inv3'))
        ..chooseWallet((await h.repository.wallets()).first);
      h.fake.nextOutcome = 'INSUFFICIENT_FUNDS';
      await flow.pay();
      expect(flow.payment!.status, 'INSUFFICIENT_FUNDS');
      expect(flow.payment!.succeeded, isFalse);
      expect((await h.repository.wallets()).first.balance, '100000.00'); // a failure moves no money
      h.fake.nextOutcome = 'SUCCEEDED';
      flow.startOver();
      await flow.pay();
      expect(flow.payment!.succeeded, isTrue);
      expect(paymentPosts(h).map((p) => p['idempotency_key']).toSet(), hasLength(2));
      expect(h.fake.created, 2);
    });

    testWidgets('every provider outcome is the server\'s answer, shown as such', (tester) async {
      final h = await signedIn(tester, (f) => f.b);
      for (final status in ['DECLINED', 'TIMEOUT', 'PROVIDER_ERROR']) {
        h.fake.nextOutcome = status;
        final flow = PaymentFlow(h.repository, childId: 'c3', invoice: await h.repository.invoice('inv3'))
          ..chooseWallet((await h.repository.wallets()).first);
        await flow.pay();
        expect(flow.payment!.status, status);
        expect(flow.payment!.outcome, contains('aucun débit'));
      }
    });

    testWidgets('security: rights, other child, other wallet, paid invoice, tampered amount, key reuse', (
      tester,
    ) async {
      final h = await signedIn(tester, (f) => f.b);
      final invoice = await h.repository.invoice('inv3');
      final wallets = await h.repository.wallets();
      // Another family's invoice: 404, like a missing one; paying for a pupil of the school
      // who is not my child: 403 (can_pay); a pupil of another school: 404.
      expect(await caught(h.repository.invoice('inv1')), isA<NotFoundException>());
      expect(await caught(h.repository.invoice('nope')), isA<NotFoundException>());
      final intruder = PaymentIntent(childId: 'c1', invoice: invoice, wallet: wallets.first);
      expect(await caught(h.repository.pay(intruder)), isA<ForbiddenException>());
      final elsewhere = PaymentIntent(childId: 'other-school', invoice: invoice, wallet: wallets.first);
      expect(await caught(h.repository.pay(elsewhere)), isA<NotFoundException>());
      // Another payer's wallet: 403.
      final foreign = await caught(
        h.api.post(
          'finance/payments/',
          body: {
            'student': 'c3',
            'amount': '40000.00',
            'payment_method': 'WALLET',
            'wallet': 'w-other',
            'invoices': ['inv3'],
            'idempotency_key': newIdempotencyKey(),
          },
        ),
      );
      expect(foreign, isA<ForbiddenException>());
      // The phone cannot change the amount: a tampered request is refused by the server.
      final tampered = await caught(
        h.api.post(
          'finance/payments/',
          body: {
            'student': 'c3',
            'amount': '90000.00',
            'payment_method': 'WALLET',
            'wallet': wallets.first.id,
            'invoices': ['inv3'],
            'idempotency_key': newIdempotencyKey(),
          },
        ),
      );
      expect((tampered as ApiException).rule, 'amount_exceeds_balance');
      expect(tampered, isA<ConflictException>());
      // Same key, different request: 409 idempotency_conflict.
      final intent = PaymentIntent(childId: 'c3', invoice: invoice, wallet: wallets.first);
      h.fake.nextOutcome = 'DECLINED';
      await h.repository.pay(intent);
      final reused = PaymentIntent(childId: 'c3', invoice: invoice, wallet: wallets.last, key: intent.key);
      expect(((await caught(h.repository.pay(reused))) as ApiException).rule, 'idempotency_conflict');
      // Paid invoice: a second payment is refused (409 invoice_not_payable).
      h.fake.nextOutcome = 'SUCCEEDED';
      await h.repository.pay(PaymentIntent(childId: 'c3', invoice: invoice, wallet: wallets.first));
      final twice = await caught(
        h.repository.pay(PaymentIntent(childId: 'c3', invoice: invoice, wallet: wallets.first)),
      );
      expect((twice as ApiException).rule, 'invoice_not_payable');
      expect(h.fake.created, 2); // the declined one + the paid one, never a second debit
    });

    testWidgets('can_pay = false: the server refuses (403) even if the app were bypassed', (tester) async {
      final h = await signedIn(tester, (f) => f.a); // Awa: Léa visible, payment NOT granted
      final invoice = await h.repository.invoice('inv1');
      // Even with a forged request (someone else's wallet id), the server refuses: can_pay is its decision.
      final forged = Wallet(
        id: 'w1',
        provider: 'FAKE',
        identifier: '690000633',
        balance: '0',
        currency: 'XAF',
        status: 'ACTIVE',
      );
      final denied = await caught(h.repository.pay(PaymentIntent(childId: 'c1', invoice: invoice, wallet: forged)));
      expect(denied, isA<ForbiddenException>());
      expect(h.fake.created, 0);
    });
  });

  group('screens', () {
    testWidgets('Finance -> invoice -> détail -> confirmation -> paiement -> résultat -> reçu -> historique', (
      tester,
    ) async {
      final h = await openPayment(tester);
      expect(find.text('Zoé Ndiaye'), findsOneWidget);
      expect(find.text('FAC-2026-0003'), findsOneWidget);
      expect(find.text('Scolarité'), findsOneWidget); // motif
      expect(find.text('30/09/2026'), findsOneWidget); // échéance
      expect(find.text('À payer'), findsOneWidget);
      expect(tester.widget<Text>(find.byKey(const Key('pay.amount'))).data, '40${nbsp}000 XAF');
      expect(find.byType(TextField), findsNothing); // no amount can be typed
      expect(find.text('FAKE ••0633'), findsOneWidget);
      expect(find.text('Portefeuille bloqué'), findsOneWidget); // shown, not selectable

      // Confirmation required; cancelling debits nothing.
      await tester.tap(find.byKey(const Key('pay.submit')));
      await tester.pumpAndSettle();
      expect(find.textContaining('seront débités du portefeuille FAKE ••0633 pour Zoé Ndiaye'), findsOneWidget);
      await tester.tap(find.byKey(const Key('pay.cancel')));
      await tester.pumpAndSettle();
      expect(paymentPosts(h), isEmpty);

      await confirmPayment(tester);
      expect(find.text('Paiement réussi'), findsOneWidget);
      expect(find.text('PAY-0002'), findsOneWidget);
      await tester.tap(find.byKey(const Key('pay.receipt')));
      await tester.pumpAndSettle();
      expect(h.pdfs.files.keys, ['recu-PAY-0002.pdf']);
      expect(h.pdfs.opened, ['memory://recu-PAY-0002.pdf']);
      expect(find.text('Reçu PAY-0002 ouvert.'), findsOneWidget);

      await tester.tap(find.byKey(const Key('pay.close')));
      await tester.pumpAndSettle();
      // Back on Finance, everything re-read from the server.
      expect(find.text('Payée'), findsWidgets);
      expect(find.textContaining('PAY-0002'), findsWidgets); // history (+ the receipt message)
      expect(find.byKey(const Key('receipt.pay2')), findsOneWidget);
      expect(find.byKey(const Key('invoice.pay.inv3')), findsNothing);
    });

    testWidgets('paying: busy, no second tap, no leaving; then the answer', (tester) async {
      final h = await openPayment(tester);
      h.fake.holdPayment = Completer<void>();
      await tester.tap(find.byKey(const Key('pay.submit')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('pay.confirm')));
      await tester.pump();
      expect(find.text('Paiement en cours…'), findsOneWidget);
      expect(find.byKey(const Key('pay.submit')), findsNothing);
      await tester.tap(find.byKey(const Key('pay.busy')), warnIfMissed: false);
      expect(tester.widget<BackButton>(find.byType(BackButton)).onPressed, isNull);
      h.fake.holdPayment!.complete();
      await tester.pumpAndSettle();
      expect(find.text('Paiement réussi'), findsOneWidget);
      expect(paymentPosts(h), hasLength(1));
    });

    testWidgets('insufficient funds: said by the server, no debit, then a new attempt', (tester) async {
      final h = await openPayment(tester);
      h.fake.nextOutcome = 'INSUFFICIENT_FUNDS';
      await confirmPayment(tester);
      expect(find.text('Solde du portefeuille insuffisant : aucun débit'), findsOneWidget);
      expect(find.byKey(const Key('pay.receipt')), findsNothing);
      h.fake.nextOutcome = 'SUCCEEDED';
      await tester.tap(find.byKey(const Key('pay.again')));
      await tester.pumpAndSettle();
      await confirmPayment(tester);
      expect(find.text('Paiement réussi'), findsOneWidget);
      expect(h.fake.created, 2);
    });

    testWidgets('answer lost: explained, « Réessayer » replays without a second debit', (tester) async {
      final h = await openPayment(tester);
      h.fake.loseNextAnswer = true;
      await confirmPayment(tester);
      expect(find.textContaining('le paiement a peut-être été enregistré'), findsOneWidget);
      await tester.tap(find.byKey(const Key('pay.retry')));
      await tester.pumpAndSettle();
      expect(find.text('Paiement réussi'), findsOneWidget);
      expect(find.textContaining('aucun second débit'), findsOneWidget);
      expect(h.fake.created, 1);
    });

    testWidgets('invoice paid meanwhile (409): explained, reloaded, nothing to pay', (tester) async {
      final h = await openPayment(tester);
      h.fake.invoices['c3']!['status'] = 'PAID'; // another payer was faster
      h.fake.invoices['c3']!['balance_due'] = '0.00';
      await confirmPayment(tester);
      expect(find.textContaining('n\'est plus à payer'), findsOneWidget);
      await tester.tap(find.byKey(const Key('pay.reload')));
      await tester.pumpAndSettle();
      expect(find.text('Cette facture est déjà réglée.'), findsOneWidget);
      expect(find.byKey(const Key('pay.submit')), findsNothing);
      expect(h.fake.created, 0);
    });

    testWidgets('receipt on a phone without PDF viewer: kept in the app, said so', (tester) async {
      final h = await openPayment(tester);
      h.pdfs.canOpen = false;
      await confirmPayment(tester);
      await tester.tap(find.byKey(const Key('pay.receipt')));
      await tester.pumpAndSettle();
      expect(h.pdfs.files.keys, ['recu-PAY-0002.pdf']);
      expect(find.textContaining('enregistré dans l\'application'), findsOneWidget);
    });

    testWidgets('session expired (or account suspended) while paying: back to login, nothing paid', (tester) async {
      final h = await openPayment(tester);
      h.fake.suspended.add('pb');
      h.fake.revokeAll(); // the server refuses access AND refresh
      await confirmPayment(tester);
      expect(h.auth.status, AuthStatus.signedOut);
      expect(h.fake.created, 0);
    });

    testWidgets('can_pay = false: amounts visible, no payment action', (tester) async {
      final h = await signedIn(tester, (f) => f.a);
      await h.tab(tester, 'Finance');
      expect(find.text('40${nbsp}000 XAF'), findsWidgets);
      await tester.tap(find.text('FAC-2026-0001'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('invoice.pay.inv1')), findsNothing);
      expect(find.textContaining('Payer'), findsNothing);
    });

    testWidgets('small phone (360 dp): the payment screen fits', (tester) async {
      final h = Harness();
      tester.view.physicalSize = const Size(720, 1280);
      tester.view.devicePixelRatio = 2.0;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(Container()); // reset
      await h.start(tester);
      tester.view.physicalSize = const Size(720, 1280);
      tester.view.devicePixelRatio = 2.0;
      await h.login(tester, h.fake.b);
      await h.tab(tester, 'Finance');
      await tester.tap(find.text('FAC-2026-0003'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('invoice.pay.inv3')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('invoice.pay.inv3')));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await confirmPayment(tester);
      expect(tester.takeException(), isNull);
      expect(find.text('Paiement réussi'), findsOneWidget);
    });
  });
}
