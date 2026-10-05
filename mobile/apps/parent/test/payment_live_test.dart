/// REAL payment journey of a parent (opt-in), with the app's services, against
/// a TEST backend (run it on the PC's LAN address to validate the LAN path):
///
///   registration -> approval -> link approved WITH can_pay -> the school opens
///   two wallets (one empty) -> obligations / invoice from the server ->
///   tampered amount refused (409) -> empty wallet: INSUFFICIENT_FUNDS recorded,
///   nothing debited -> answer "lost": the same key replays, ONE payment ->
///   invoice PAID, wallet debited once -> receipt PDF -> history -> a second
///   payment of the paid invoice refused (409) -> another pupil: 404 / 403
///
/// Same preparation as live_test.dart (backend/tools/e2e_parent_fixture.py), then:
///   PARENT_LIVE_URL=http://(IPv4 du PC):8001/api/v1/ PARENT_LIVE='(json)'
///   PARENT_LIVE_ADMIN=e2eadmin PARENT_LIVE_ADMIN_PASSWORD=(generated for the run)
///   flutter test test/payment_live_test.dart
@Tags(['live'])
library;

import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:school_core/school_core.dart';
import 'package:school_parent/data/parent_repository.dart';
import 'package:school_parent/data/payment_flow.dart';

void main() {
  final env = Platform.environment;
  final url = env['PARENT_LIVE_URL'];
  final raw = env['PARENT_LIVE'];
  final skip = url == null || raw == null || env['PARENT_LIVE_ADMIN_PASSWORD'] == null
      ? 'PARENT_LIVE_URL / PARENT_LIVE / PARENT_LIVE_ADMIN_PASSWORD not set (opt-in live test)'
      : null;

  test(
    'parent pays an invoice against the real backend',
    () async {
      final data = (jsonDecode(raw!) as Map).cast<String, dynamic>();
      final random = Random.secure();
      String token(int n) => List.generate(n, (_) => random.nextInt(36).toRadixString(36)).join();
      final password = 'Pay-${token(12)}-26!';
      final email = 'payeur.${token(6)}@e2e.test';

      final admin = ApiClient(baseUrl: url!);
      final adminAuth = AuthService(admin, MemoryTokenStore(), device: const DeviceInfo(name: 'E2E admin'));
      await adminAuth.login(env['PARENT_LIVE_ADMIN'] ?? 'e2eadmin', env['PARENT_LIVE_ADMIN_PASSWORD']!);

      final api = ApiClient(baseUrl: url);
      final auth = AuthService(api, MemoryTokenStore(), requiredRole: 'PARENT', allowPending: true);
      final repo = ParentRepository(api);

      // 1. Account approved, child linked WITH the right to pay.
      await repo.register(
        firstName: 'Bibi',
        lastName: 'Payeur',
        email: email,
        password: password,
        schoolCode: data['school_code'],
      );
      await auth.login(email, password);
      final pending = await admin.page('admin/registrations/', params: {'status': 'PENDING', 'search': email});
      await admin.post('admin/registrations/${pending.rows.single['id']}/approve/');
      await auth.reloadIdentity();
      final request = await repo.requestLink(
        studentNumber: data['student_number'],
        dateOfBirth: DateTime.parse(data['date_of_birth']),
        relationship: 'FATHER',
        documentType: 'CNI',
        documentNumber: 'CM 5566-7788',
      );
      final linkUrl = 'admin/link-requests/${request.id}/';
      await admin.post('${linkUrl}verify-identity/', body: {'document_type': 'CNI', 'document_number': 'CM 5566-7788'});
      await admin.post('${linkUrl}student-approval/', body: {'decision': 'APPROVED', 'note': 'E2E paiement'});
      await admin.post('${linkUrl}approve/', body: {'can_view_financial_data': true, 'can_pay': true});
      final child = (await repo.children()).single;
      expect((child.canViewFinance, child.canPay), (true, true));

      // 2. The school opens two wallets for this payer: one funded, one empty.
      final me = auth.identity!.current!.id;
      Future<Map> wallet(String suffix) async =>
          await admin.post(
                'admin/finance/wallets/',
                body: {'owner': me, 'provider_code': 'E2E', 'wallet_identifier': '69${token(7)}$suffix'},
              )
              as Map;
      final funded = await wallet('1');
      await wallet('2');
      await admin.post('admin/finance/wallets/${funded['id']}/fund/', body: {'amount': '200000.00'});

      // 3. What is owed: the server's numbers.
      final obligations = await repo.obligations(child.id);
      expect(obligations.canPay, isTrue);
      final invoice = obligations.openInvoices.single;
      expect(invoice.balance, '75000.00');
      final wallets = await repo.wallets();
      expect(wallets, hasLength(2)); // MY wallets only
      final rich = wallets.firstWhere((w) => w.id == funded['id']);
      final empty = wallets.firstWhere((w) => w.id != funded['id']);

      // 4. The phone cannot raise the amount: the server refuses a tampered request.
      final tampered = await _caught(
        api.post(
          'finance/payments/',
          body: {
            'student': child.id,
            'amount': '90000.00',
            'payment_method': 'WALLET',
            'wallet': rich.id,
            'invoices': [invoice.id],
            'idempotency_key': newIdempotencyKey(),
          },
        ),
      );
      expect((tampered as ApiException).rule, 'amount_exceeds_balance');

      // 5. Empty wallet: a RESULT recorded by the server, nothing debited.
      final poor = PaymentFlow(repo, childId: child.id, invoice: invoice)..chooseWallet(empty);
      await poor.pay();
      expect(poor.payment!.status, 'INSUFFICIENT_FUNDS');
      expect((await repo.invoice(invoice.id)).balance, '75000.00');

      // 6. Payment; the answer "is lost": the retry with the SAME key replays it.
      final intent = PaymentIntent(childId: child.id, invoice: invoice, wallet: rich);
      final paid = await repo.pay(intent);
      expect((paid.succeeded, paid.replayed), (true, false));
      final replay = await repo.pay(intent);
      expect((replay.id, replay.replayed), (paid.id, true));
      expect((await repo.invoice(invoice.id)).status, 'PAID');
      expect((await repo.wallets()).firstWhere((w) => w.id == rich.id).balance, '125000.00'); // debited ONCE

      // 7. Receipt (official PDF of the school) and history.
      final pdf = await repo.receiptPdf(paid.id);
      expect(ascii.decode(pdf.sublist(0, 5)), '%PDF-');
      final history = await repo.payments(child.id);
      expect(history.where((p) => p.succeeded).map((p) => p.reference), [paid.reference]);
      expect(history.where((p) => p.status == 'INSUFFICIENT_FUNDS'), hasLength(1));

      // 8. Paying the paid invoice again (new key) is refused.
      final again = await _caught(repo.pay(PaymentIntent(childId: child.id, invoice: invoice, wallet: rich)));
      expect((again as ApiException).rule, 'invoice_not_payable');

      // 9. Another pupil of the school (not linked): hidden (404), and paying for him is refused (403).
      final other = data['other_student_id'] as String;
      expect(await _caught(repo.obligations(other)), isA<NotFoundException>());
      expect(
        await _caught(repo.pay(PaymentIntent(childId: other, invoice: invoice, wallet: rich))),
        isA<ForbiddenException>(),
      );

      await auth.logout();
      await adminAuth.logout();
    },
    skip: skip,
    timeout: const Timeout(Duration(minutes: 3)),
  );
}

Future<Object?> _caught(Future<Object?> future) async {
  try {
    await future;
    return null;
  } on Object catch (error) {
    return error;
  }
}
