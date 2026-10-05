/// Everything the parent app reads or does, through the API only. The
/// server decides which child this parent may see (VERIFIED link) and with
/// which rights (can_view_financial_data, can_pay...): the app never filters
/// or grants anything itself — a child id the parent is not linked to is a
/// 404, a right not granted is a 403.
///
///   POST /registrations/parent/            public (same answer whatever happens)
///   GET  /registrations/me/                state of my registration (pending account)
///   GET  /parents/children/                my verified children (+ current schooling)
///   GET/POST /parents/link-requests/       « this is my child » (document number -> HMAC server side)
///   POST /parents/link-requests/{id}/sponsor/ | /cancel/
///   POST /parents/children/{id}/sponsor-codes/   one-time code for a second parent
///   GET  /parents/children/{id}/teachers/  who I may write to about this child
///   GET  /students/{id}/attendance/  …/scans/  (never who scanned)   GET /parents/convocations/
///   GET  /students/{id}/sessions/?date_from&date_to
///   GET  /finance/students/{id}/obligations/  /finance/invoices/?student=  /finance/invoices/{id}/
///   GET  /finance/payments/?student=   GET /finance/wallets/ (my own wallets)
///   POST /finance/payments/            {student, amount = the invoice's balance_due as given by the
///                                       server, WALLET, wallet, invoices, idempotency_key}
///   GET  /report-cards/?student=  (validated only for parents)   GET /report-cards/{id}/pdf/
///   GET  /payments/{id}/receipt.pdf/        GET /documents/verify/?code=
///   communication: CommunicationRepository (school_core)
library;

import 'dart:typed_data';

import 'package:intl/intl.dart';
import 'package:school_core/school_core.dart';

import '../models/models.dart';
import 'payment_flow.dart';

final _day = DateFormat('yyyy-MM-dd');

class SponsorCode {
  SponsorCode(this.code, this.expiresAt);

  final String code; // shown once, never stored by the app
  final DateTime? expiresAt;
}

class ParentRepository extends CommunicationRepository {
  ParentRepository(super.api);

  // --- account ------------------------------------------------------------------------

  /// Public registration: the server answers the same way whether or not the
  /// e-mail is already used (no account enumeration). The password is sent
  /// once over the connection and never kept by the app.
  Future<void> register({
    required String firstName,
    required String lastName,
    required String email,
    required String password,
    String? phone,
    String? schoolCode, // V1 runs one school: only needed when the server hosts several
  }) => api.post(
    'registrations/parent/',
    auth: false,
    body: {
      'first_name': firstName.trim(),
      'last_name': lastName.trim(),
      'email': email.trim(),
      'password': password,
      if (phone != null && phone.trim().isNotEmpty) 'phone': phone.trim(),
      'school_code': ?schoolCode,
    },
  );

  Future<List<Registration>> registrations() async => ((await api.get('registrations/me/') as List?) ?? const [])
      .map((r) => Registration.fromJson((r as Map).cast<String, dynamic>()))
      .toList();

  // --- children and links -----------------------------------------------------------

  Future<List<Child>> children() async => (await api.listAll('parents/children/')).map(Child.fromJson).toList();

  Future<List<LinkRequest>> linkRequests() async =>
      (await api.listAll('parents/link-requests/')).map(LinkRequest.fromJson).toList();

  Future<LinkRequest> requestLink({
    required String studentNumber,
    required DateTime dateOfBirth,
    required String relationship,
    required String documentType,
    required String documentNumber,
  }) async => LinkRequest.fromJson(
    (await api.post(
              'parents/link-requests/',
              body: {
                'student_number': studentNumber.trim(),
                'date_of_birth': _day.format(dateOfBirth),
                'relationship_type': relationship,
                'document_type': documentType,
                'document_number': documentNumber.trim(),
              },
            )
            as Map)
        .cast<String, dynamic>(),
  );

  Future<LinkRequest> sponsor(String requestId, String code) async => LinkRequest.fromJson(
    (await api.post('parents/link-requests/$requestId/sponsor/', body: {'code': code.trim()}) as Map)
        .cast<String, dynamic>(),
  );

  Future<LinkRequest> cancelRequest(String requestId) async =>
      LinkRequest.fromJson((await api.post('parents/link-requests/$requestId/cancel/') as Map).cast<String, dynamic>());

  Future<SponsorCode> sponsorCode(String childId) async {
    final data = (await api.post('parents/children/$childId/sponsor-codes/') as Map).cast<String, dynamic>();
    return SponsorCode('${data['code']}', schoolTime(data['expires_at']));
  }

  Future<List<TeacherContact>> teachers(String childId) async =>
      ((await api.get('parents/children/$childId/teachers/') as List?) ?? const [])
          .map((t) => TeacherContact.fromJson((t as Map).cast<String, dynamic>()))
          .toList();

  // --- school life --------------------------------------------------------------------

  Future<AttendanceReport> attendance(String childId) async =>
      AttendanceReport.fromJson((await api.get('students/$childId/attendance/') as Map).cast<String, dynamic>());

  Future<List<Scan>> scans(String childId) async =>
      (await api.page('students/$childId/scans/', pageSize: 20)).rows.map(Scan.fromJson).toList();

  Future<List<Convocation>> convocations() async =>
      (await api.listAll('parents/convocations/')).map(Convocation.fromJson).toList();

  Future<List<ClassSession>> sessions(String childId, DateTime from, DateTime to) async {
    final rows = await api.listAll(
      'students/$childId/sessions/',
      params: {'date_from': _day.format(from), 'date_to': _day.format(to)},
    );
    return rows.map(ClassSession.fromJson).toList()
      ..sort((a, b) => (a.start ?? DateTime(0)).compareTo(b.start ?? DateTime(0)));
  }

  // --- finance (the server enforces can_view_financial_data / can_pay) -------------

  Future<Obligations> obligations(String childId) async =>
      Obligations.fromJson((await api.get('finance/students/$childId/obligations/') as Map).cast<String, dynamic>());

  Future<List<Invoice>> invoices(String childId) async =>
      (await api.listAll('finance/invoices/', params: {'student': childId})).map(Invoice.fromJson).toList();

  Future<List<Payment>> payments(String childId) async =>
      (await api.listAll('finance/payments/', params: {'student': childId})).map(Payment.fromJson).toList();

  Future<Invoice> invoice(String invoiceId) async =>
      Invoice.fromJson((await api.get('finance/invoices/$invoiceId/') as Map).cast<String, dynamic>());

  /// The caller's OWN wallets (the server never returns another payer's).
  Future<List<Wallet>> wallets() async => (await api.listAll('finance/wallets/')).map(Wallet.fromJson).toList();

  /// Pays [intent]: the amount is the invoice's balance_due exactly as the server gave it
  /// (a string, never typed nor recomputed here). Same [PaymentIntent] = same
  /// idempotency key: a retry after a lost answer returns the payment already made.
  Future<Payment> pay(PaymentIntent intent) async => Payment.fromJson(
    (await api.post(
              'finance/payments/',
              body: {
                'student': intent.childId,
                'amount': intent.invoice.balance,
                'payment_method': 'WALLET',
                'wallet': intent.wallet.id,
                'invoices': [intent.invoice.id],
                'idempotency_key': intent.key,
              },
            )
            as Map)
        .cast<String, dynamic>(),
  );

  // --- report cards and documents -------------------------------------------------------

  Future<List<ReportCard>> reportCards(String childId) async =>
      (await api.listAll('report-cards/', params: {'student': childId})).map(ReportCard.fromJson).toList();

  /// The official PDF, built by the server with the SCHOOL's branding.
  Future<Uint8List> reportCardPdf(String reportCardId) => api.download('report-cards/$reportCardId/pdf/');

  Future<Uint8List> receiptPdf(String paymentId) => api.download('payments/$paymentId/receipt.pdf/');

  Future<DocumentCheck> verifyDocument(String code) async => DocumentCheck.fromJson(
    (await api.get('documents/verify/', params: {'code': code.trim()}) as Map).cast<String, dynamic>(),
  );
}
