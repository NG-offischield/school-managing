/// In-memory fake of the Django API for the parent widget tests. It
/// reproduces the CONTRACT the app relies on — envelope, tokens, a pending
/// membership, visibility limited to VERIFIED children (another child is a
/// 404), financial rights per link (403 without can_view_financial_data),
/// validated report cards only — not the backend's logic.
library;

import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:intl/intl.dart';

final _day = DateFormat('yyyy-MM-dd');

http.Response ok(Object? data, {int status = 200, Map<String, dynamic>? meta}) => http.Response.bytes(
  utf8.encode(jsonEncode({'success': true, 'data': data, 'message': null, 'meta': meta})),
  status,
  headers: {'content-type': 'application/json'},
);

http.Response page(List<Object?> rows) => ok(rows, meta: {'count': rows.length, 'next': null});

http.Response fail(int status, String code, {Map<String, dynamic>? details}) => http.Response.bytes(
  utf8.encode(
    jsonEncode({
      'success': false,
      'error': {'code': code, 'message': code, 'details': ?details},
    }),
  ),
  status,
  headers: {'content-type': 'application/json'},
);

class FakePerson {
  FakePerson(this.key, this.first, this.last, this.email, {this.roles = const ['PARENT'], this.status = 'ACTIVE'});

  final String key;
  final String first;
  final String last;
  final String email;
  List<String> roles;
  String status; // membership status
  String password = 'Parent-Kribi-2026!';

  String get name => '$first $last';
}

Map<String, dynamic> _child(String id, String first, String last, String klass, {bool view = true, bool pay = false}) =>
    {
      'id': 'link-$id',
      'student': {'id': id, 'first_name': first, 'last_name': last, 'student_number': 'MAT-$id'},
      'relationship_type': 'MOTHER',
      'can_view_financial_data': view,
      'can_pay': pay,
      'can_receive_notifications': true,
      'can_submit_complaints': true,
      'enrollment': {'class_name': klass, 'academic_year_name': '2026-2027', 'status': 'ACTIVE'},
    };

class FakeApi {
  FakeApi() {
    children = {
      a.key: [
        _child('c1', 'Léa', 'Mbarga', '6e A', view: true, pay: false),
        _child('c2', 'Tom', 'Mbarga', '3e B', view: false),
      ],
      b.key: [_child('c3', 'Zoé', 'Ndiaye', '4e C', view: true, pay: true)],
    };
  }

  final a = FakePerson('pa', 'Awa', 'Mbarga', 'awa@parents.test');
  final b = FakePerson('pb', 'Paul', 'Ndiaye', 'paul@parents.test');
  final teacher = FakePerson('tj', 'Jean', 'Prof', 'jean@ecole.test', roles: const ['TEACHER']);
  final registered = <FakePerson>[];
  late Map<String, List<Map<String, dynamic>>> children;
  final linkRequests = <Map<String, dynamic>>[];
  final conversations = <Map<String, dynamic>>[];
  final complaints = <Map<String, dynamic>>[];
  final requests = <http.Request>[];
  final tokens = <String, FakePerson>{};
  final refreshes = <String, FakePerson>{};
  final suspended = <String>{};
  String? issuedSponsorCode;
  bool offline = false;
  int issued = 0;

  List<FakePerson> get people => [a, b, teacher, ...registered];

  Map<String, dynamic> _issue(FakePerson who) {
    issued++;
    tokens['acc-$issued'] = who;
    refreshes['ref-$issued'] = who;
    return {'access_token': 'acc-$issued', 'refresh_token': 'ref-$issued', 'access_expires_in': 900};
  }

  void revokeAll() {
    tokens.clear();
    refreshes.clear();
  }

  String _at(int dayOffset, int hour) {
    final day = DateTime.now().add(Duration(days: dayOffset));
    return '${_day.format(day)}T${hour.toString().padLeft(2, '0')}:00:00+01:00';
  }

  Future<http.Response> call(http.Request request) async {
    requests.add(request);
    if (offline) throw http.ClientException('offline');
    final path = request.url.path.replaceFirst('/api/v1/', '');
    final params = request.url.queryParameters;
    final body = request.body.isEmpty ? <String, dynamic>{} : (jsonDecode(request.body) as Map).cast<String, dynamic>();

    // --- public ---------------------------------------------------------------------
    switch (path) {
      case 'auth/login/':
        final who = people.where((p) => p.email == body['identifier']).firstOrNull;
        if (who == null || who.password != body['password'] || suspended.contains(who.key)) {
          return fail(401, 'INVALID_CREDENTIALS');
        }
        return ok(_issue(who));
      case 'auth/refresh/':
        final who = refreshes.remove(body['refresh_token']);
        return who == null || suspended.contains(who.key) ? fail(401, 'INVALID_REFRESH_TOKEN') : ok(_issue(who));
      case 'registrations/parent/':
        if ('${body['password']}'.length < 10) {
          return fail(
            400,
            'VALIDATION_ERROR',
            details: {
              'password': ['Ce mot de passe est trop court. Il doit contenir au minimum 10 caractères.'],
            },
          );
        }
        // Same answer whether or not the e-mail exists (no enumeration).
        if (people.every((p) => p.email != body['email'])) {
          registered.add(
            FakePerson(
              'new${registered.length}',
              '${body['first_name']}',
              '${body['last_name']}',
              '${body['email']}',
              roles: const [],
              status: 'PENDING',
            )..password = '${body['password']}',
          );
        }
        return ok({'status': 'RECEIVED'}, status: 202);
    }

    // --- authenticated --------------------------------------------------------------
    final who = tokens[request.headers['Authorization']?.replaceFirst('Bearer ', '')];
    if (who == null) return fail(401, 'INVALID_ACCESS_TOKEN');
    if (path == 'auth/logout/') {
      tokens.removeWhere((_, p) => p == who);
      return ok(null);
    }
    if (path == 'auth/me/') {
      return ok({
        'id': 'u-${who.key}',
        'username': who.email,
        'first_name': who.first,
        'last_name': who.last,
        'memberships': [
          {
            'id': 'm-${who.key}',
            'school_code': 'E1',
            'school_name': 'École Les Palmiers',
            'status': who.status,
            'is_primary_school': true,
            'roles': who.roles,
          },
        ],
      });
    }
    if (path == 'registrations/me/') {
      return ok([
        if (registered.contains(who))
          {
            'id': 'r-${who.key}',
            'status': who.status == 'ACTIVE' ? 'APPROVED' : 'PENDING',
            'applicant_name': who.name,
            'applicant_email': who.email,
            'school_name': 'École Les Palmiers',
            'submitted_at': _at(0, 8),
          },
      ]);
    }
    // Everything below needs an ACTIVE membership (like the server's tenancy).
    if (who.status != 'ACTIVE') return fail(403, 'NO_ACTIVE_MEMBERSHIP');

    final mine = children[who.key] ?? const [];
    final mineIds = {for (final c in mine) (c['student'] as Map)['id']};
    Map<String, dynamic>? link(String id) => mine.where((c) => (c['student'] as Map)['id'] == id).firstOrNull;

    if (path == 'parents/children/') return page(mine);
    if (path == 'parents/link-requests/') {
      if (request.method == 'POST') {
        if (body['student_number'] != 'MAT-NEW' || body['date_of_birth'] != '2015-03-12') {
          return fail(400, 'BUSINESS_RULE_VIOLATION', details: {'rule': 'student_not_found'});
        }
        final row = {
          'id': 'lr${linkRequests.length + 1}',
          'owner': who.key,
          'student': {'id': 'c9', 'name': 'Nina Mbarga', 'student_number': 'MAT-NEW'},
          'relationship_type': body['relationship_type'],
          'status': 'PENDING',
          'student_approval_status': 'PENDING',
          'identity_status': 'PENDING',
          'identity_method': 'ID_DOCUMENT',
          'document_type': body['document_type'],
          'sponsored': false,
          'created_at': _at(0, 9),
        };
        linkRequests.add(row);
        return ok(row, status: 201);
      }
      return page(linkRequests.where((r) => r['owner'] == who.key).toList());
    }
    if (path.startsWith('parents/link-requests/')) {
      final parts = path.split('/');
      final row = linkRequests.where((r) => r['id'] == parts[2] && r['owner'] == who.key).firstOrNull;
      if (row == null) return fail(404, 'NOT_FOUND');
      if (parts[3] == 'cancel') {
        row['status'] = 'CANCELLED';
        return ok(row);
      }
      if (body['code'] != issuedSponsorCode) {
        return fail(400, 'BUSINESS_RULE_VIOLATION', details: {'rule': 'sponsor_code_invalid'});
      }
      row
        ..['sponsored'] = true
        ..['identity_status'] = 'VERIFIED'
        ..['identity_method'] = 'SPONSOR_2FA';
      return ok(row);
    }
    if (path.startsWith('parents/children/')) {
      final id = path.split('/')[2];
      if (!mineIds.contains(id)) return fail(404, 'NOT_FOUND');
      if (path.endsWith('/sponsor-codes/')) {
        issuedSponsorCode = 'K7Q2-M9XA';
        return ok({'code': issuedSponsorCode, 'expires_at': _at(0, 23)}, status: 201);
      }
      return ok([
        {
          'member': 'm-tj',
          'name': 'Jean Prof',
          'subjects': ['MATH'],
        },
      ]);
    }
    if (path == 'parents/convocations/') {
      return page(
        who == a
            ? [
                {
                  'id': 'cv1',
                  'student': 'c1',
                  'scheduled_start': _at(2, 10),
                  'scheduled_end': _at(2, 11),
                  'reason': 'Retards répétés',
                  'status': 'SCHEDULED',
                },
              ]
            : [],
      );
    }
    if (path.startsWith('students/')) {
      final id = path.split('/')[1];
      if (!mineIds.contains(id)) return fail(404, 'NOT_FOUND'); // another child: like a missing one
      if (path.endsWith('/attendance/')) {
        return ok({
          'student': id,
          'summary': {
            'unexcused_absence_hours': '4.00',
            'excused_absence_hours': '2.00',
            'late_count': 1,
            'alert_level': 'YELLOW',
          },
          'records': [
            {'date': _day.format(DateTime.now()), 'status': 'LATE', 'arrival_time': '07:45:00', 'late_minutes': 15},
            {
              'date': _day.format(DateTime.now().subtract(const Duration(days: 1))),
              'status': 'ABSENT',
              'absence_hours': '4.00',
            },
          ],
        });
      }
      if (path.endsWith('/scans/')) {
        return page([
          {'id': 'sc1', 'scanned_at': _at(0, 7), 'result': 'ACCEPTED'},
        ]);
      }
      if (path.endsWith('/sessions/')) {
        Map<String, dynamic> session(String sid, String subject, int day, int hour, {String status = 'SCHEDULED'}) => {
          'id': sid,
          'subject': {'id': 's-$subject', 'code': subject, 'name': subject == 'MATH' ? 'Mathématiques' : 'Français'},
          'school_class': {'id': 'k1', 'name': (link(id)!['enrollment'] as Map)['class_name']},
          'teacher': {'id': 't1', 'name': 'Jean Prof'},
          'room': {'id': 'r1', 'code': 'R12', 'name': 'Salle 12'},
          'date': _day.format(DateTime.now().add(Duration(days: day))),
          'scheduled_start': _at(day, hour),
          'scheduled_end': _at(day, hour + 1),
          'status': status,
          'is_substituted': subject == 'FR',
          'is_moved': false,
        };
        final from = params['date_from']!, to = params['date_to']!;
        final rows = [
          session('se1', 'MATH', 0, 8),
          session('se2', 'FR', 0, 10),
          session('se3', 'MATH', 0, 14, status: 'CANCELLED'),
        ].where((s) => '${s['date']}'.compareTo(from) >= 0 && '${s['date']}'.compareTo(to) <= 0).toList();
        return page(rows);
      }
    }
    if (path.startsWith('finance/students/')) {
      final id = path.split('/')[2];
      final row = link(id);
      if (row == null) return fail(404, 'NOT_FOUND');
      if (row['can_view_financial_data'] != true) return fail(403, 'PERMISSION_DENIED');
      final invoice = invoices[id];
      final open = invoice != null && _payable(invoice);
      return ok({
        'student': id,
        'currency': 'XAF',
        'balance_due': open ? invoice['balance_due'] : '0.00',
        'solvency': open ? 'OVERDUE' : 'UP_TO_DATE',
        'can_pay': row['can_pay'],
        'open_invoices': [if (open) invoice],
      });
    }
    if (path == 'finance/invoices/') {
      final row = link(params['student'] ?? '');
      final invoice = invoices[params['student']];
      return page(row != null && row['can_view_financial_data'] == true && invoice != null ? [invoice] : []);
    }
    if (path.startsWith('finance/invoices/')) {
      final id = path.split('/')[2];
      final entry = invoices.entries.where((e) => e.value['id'] == id).firstOrNull;
      // Another family's or another school's invoice: like a missing one.
      if (entry == null || link(entry.key)?['can_view_financial_data'] != true) return fail(404, 'NOT_FOUND');
      return ok(entry.value);
    }
    if (path == 'finance/wallets/') return page(wallets[who.key] ?? const []); // MY wallets only
    if (path == 'finance/payments/' && request.method == 'POST') {
      await holdPayment?.future; // the provider takes its time: the phone shows « en cours »
      return _pay(who, body, link);
    }
    if (path == 'finance/payments/') {
      final student = params['student'];
      final row = link(student ?? '');
      return page(
        payments
            .where(
              (p) =>
                  p['student'] == student &&
                  row != null &&
                  (row['can_view_financial_data'] == true || p['payer'] == 'm-${who.key}'),
            )
            .toList()
            .reversed
            .toList(),
      );
    }
    if (path == 'report-cards/') {
      // The server gives parents VALIDATED report cards of their verified children only.
      return page(
        mineIds.contains(params['student'])
            ? [
                {
                  'id': 'rc1',
                  'period_name': 'Trimestre 1',
                  'status': 'VALIDATED',
                  'general_average': '14.25',
                  'scale_max_score': '20.00',
                  'rank': 5,
                  'class_size': 32,
                  'validated_at': _at(-10, 12),
                  'lines': [
                    {'subject_name': 'Mathématiques', 'average': '15.00', 'coefficient': '4.00'},
                  ],
                },
              ]
            : [],
      );
    }
    if (path.startsWith('payments/') && path.endsWith('/receipt.pdf/')) {
      final id = path.split('/')[1];
      final payment = payments.where((p) => p['id'] == id).firstOrNull;
      if (payment == null || link('${payment['student']}') == null) return fail(404, 'NOT_FOUND');
      if (payment['status'] != 'SUCCEEDED') {
        return fail(409, 'CONFLICT', details: {'rule': 'document_source_not_final'});
      }
      return http.Response.bytes(
        utf8.encode('%PDF-1.4 receipt $id'),
        200,
        headers: {'content-type': 'application/pdf'},
      );
    }
    if (path == 'report-cards/rc1/pdf/') {
      return http.Response.bytes(utf8.encode('%PDF-1.4 fake'), 200, headers: {'content-type': 'application/pdf'});
    }
    if (path == 'documents/verify/') {
      return params['code'] == 'ABCD-1234'
          ? ok({'valid': true, 'kind': 'REPORT_CARD', 'status': 'OFFICIAL', 'current': true, 'title': 'Bulletin T1'})
          : fail(404, 'NOT_FOUND');
    }
    if (path == 'notifications/') {
      return page([
        {
          'id': 'n1',
          'notification_type': 'ATTENDANCE_LATE',
          'severity': 'WARNING',
          'title': 'Retard de Léa',
          'message': 'Arrivée à 07:45.',
          'is_read': false,
          'created_at': _at(0, 7),
        },
      ]);
    }
    if (path == 'notifications/unread-count/') return ok({'unread': 1});
    if (path == 'conversations/') {
      if (request.method == 'POST') {
        if (body['conversation_type'] == 'PARENT_TEACHER' && !mineIds.contains(body['student'])) {
          return fail(404, 'NOT_FOUND');
        }
        final row = {
          'id': 'conv${conversations.length + 1}',
          'conversation_type': body['conversation_type'],
          'title': body['title'] ?? '',
          'student': body['student'],
          'participants': [
            {'member': 'm-${who.key}', 'name': who.name},
          ],
          'unread_count': 0,
          'last_message_at': _at(0, 9),
          'first': body['body'],
        };
        conversations.add(row);
        return ok(row, status: 201);
      }
      return page(conversations);
    }
    if (path.startsWith('conversations/') && path.endsWith('/messages/')) {
      final row = conversations.where((c) => c['id'] == path.split('/')[1]).firstOrNull;
      if (row == null) return fail(404, 'NOT_FOUND');
      return page([
        {
          'id': 'msg-${row['id']}',
          'conversation': row['id'],
          'sender_name': who.name,
          'body': row['first'],
          'created_at': _at(0, 9),
          'attachments': <Map>[],
        },
      ]);
    }
    if (path.startsWith('conversations/') && path.endsWith('/read/')) return ok({'read': true});
    if (path == 'complaints/') {
      if (request.method == 'POST') {
        final row = {
          'id': 'cp${complaints.length + 1}',
          'subject': body['subject'],
          'description': body['description'],
          'status': 'OPEN',
          'student': body['student'],
          'created_at': _at(0, 9),
        };
        complaints.add(row);
        return ok(row, status: 201);
      }
      return page(complaints);
    }
    return fail(404, 'NOT_FOUND');
  }

  // --- finance: the SERVER's state and rules (ADR 0013), the app computes nothing ---------

  /// Invoice of each child (by student id), mutated by payments like the server's.
  late final invoices = <String, Map<String, dynamic>>{
    'c1': _invoiceOf('inv1', 'FAC-2026-0001', total: 100000, paid: 60000),
    'c3': _invoiceOf('inv3', 'FAC-2026-0003', total: 40000, paid: 0),
  };

  /// Wallets by owner (opened by the school): Paul has an active one and a blocked one.
  final wallets = <String, List<Map<String, dynamic>>>{
    'pb': [
      _wallet('w1', 'pb', '690000633', '100000.00', 'ACTIVE'),
      _wallet('w2', 'pb', '690000999', '5000.00', 'BLOCKED'),
    ],
  };

  late final payments = <Map<String, dynamic>>[
    _payment('pay1', 'PAY-0001', 'c1', 'm-pa', 'w0', '60000.00', 'SUCCEEDED', ['FAC-2026-0001']),
  ];
  final _byKey = <String, (String, Map<String, dynamic>)>{};

  /// Outcome the simulated provider gives to the next NEW payment.
  String nextOutcome = 'SUCCEEDED';

  /// Holds the answer of POST /finance/payments/ until completed.
  Completer<void>? holdPayment;

  /// The next payment is processed, but its answer never reaches the phone.
  bool loseNextAnswer = false;

  /// Payments really created by the server (replays excluded).
  int get created => payments.length - 1;

  static String _money(num value) => value.toStringAsFixed(2);

  static Map<String, dynamic> _wallet(String id, String owner, String number, String balance, String status) => {
    'id': id,
    'owner': 'm-$owner',
    'wallet_type': 'SIMULATION',
    'provider_code': 'FAKE',
    'wallet_identifier': number,
    'balance': balance,
    'currency': 'XAF',
    'status': status,
  };

  Map<String, dynamic> _invoiceOf(String id, String number, {required num total, required num paid}) => {
    'id': id,
    'invoice_number': number,
    'status': paid == 0 ? 'ISSUED' : (paid >= total ? 'PAID' : 'PARTIALLY_PAID'),
    'issue_date': '2026-09-01',
    'due_date': '2026-09-30',
    'total_amount': _money(total),
    'amount_paid': _money(paid),
    'balance_due': _money(total - paid),
    'currency': 'XAF',
    'lines': [
      {'fee_type_code': 'TUITION', 'description': 'Scolarité', 'total': _money(total)},
    ],
  };

  Map<String, dynamic> _payment(
    String id,
    String reference,
    String student,
    String payer,
    String wallet,
    String amount,
    String status,
    List<String> invoiceNumbers,
  ) => {
    'id': id,
    'payment_reference': reference,
    'student': student,
    'payer': payer,
    'wallet': wallet,
    'amount': amount,
    'currency': 'XAF',
    'payment_method': 'WALLET',
    'status': status,
    'initiated_at': _at(0, 9),
    'completed_at': _at(0, 9),
    'failure_reason': status == 'SUCCEEDED' ? '' : 'Simulation : $status',
    'allocations': [
      if (status == 'SUCCEEDED')
        for (final n in invoiceNumbers) {'invoice_number': n},
    ],
  };

  static bool _payable(Map<String, dynamic> invoice) =>
      invoice['status'] == 'ISSUED' || invoice['status'] == 'PARTIALLY_PAID';

  /// POST /finance/payments/ — same rules and answers as the server (ADR 0013 §4-§8).
  http.Response _pay(FakePerson who, Map<String, dynamic> body, Map<String, dynamic>? Function(String) link) {
    final student = '${body['student']}';
    final key = '${body['idempotency_key'] ?? ''}';
    if (key.isEmpty) {
      return fail(
        400,
        'VALIDATION_ERROR',
        details: {
          'idempotency_key': ['Required.'],
        },
      );
    }
    final row = link(student);
    // A pupil of this school I may not pay for (not my child, or no can_pay): 403,
    // like the server (services.can_pay); a pupil unknown here (other school): 404.
    final known = children.values.expand((c) => c).any((c) => (c['student'] as Map)['id'] == student);
    if (row == null) return fail(known ? 403 : 404, known ? 'PERMISSION_DENIED' : 'NOT_FOUND');
    if (row['can_pay'] != true) return fail(403, 'PERMISSION_DENIED');
    final fingerprint = '$student|${body['amount']}|${body['payment_method']}|${body['wallet']}|${body['invoices']}';
    final previous = _byKey[key];
    if (previous != null) {
      if (previous.$1 != fingerprint) {
        return fail(409, 'CONFLICT', details: {'rule': 'idempotency_conflict'});
      }
      return ok({...previous.$2, 'replayed': true}); // 200: the payment already made, no new debit
    }
    final wallet = (wallets[who.key] ?? const []).where((w) => w['id'] == body['wallet']).firstOrNull;
    if (wallet == null) return fail(403, 'PERMISSION_DENIED'); // only my own wallet
    final invoiceIds = (body['invoices'] as List).cast<String>();
    final invoice = invoices[student];
    if (invoice == null || !invoiceIds.contains(invoice['id'])) {
      return fail(400, 'BUSINESS_RULE_VIOLATION', details: {'rule': 'invoice_other_student'});
    }
    if (!_payable(invoice)) return fail(409, 'CONFLICT', details: {'rule': 'invoice_not_payable'});
    final amount = num.parse('${body['amount']}');
    if (amount > num.parse('${invoice['balance_due']}')) {
      return fail(409, 'CONFLICT', details: {'rule': 'amount_exceeds_balance'});
    }
    var status = nextOutcome;
    if (wallet['status'] != 'ACTIVE') status = 'DECLINED';
    if (status == 'SUCCEEDED' && num.parse('${wallet['balance']}') < amount) status = 'INSUFFICIENT_FUNDS';
    final payment = _payment(
      'pay${payments.length + 1}',
      'PAY-${(payments.length + 1).toString().padLeft(4, '0')}',
      student,
      'm-${who.key}',
      '${wallet['id']}',
      _money(amount),
      status,
      ['${invoice['invoice_number']}'],
    );
    payments.add(payment);
    _byKey[key] = (fingerprint, payment);
    if (status == 'SUCCEEDED') {
      // Only a success moves money (wallet debited, invoice settled).
      wallet['balance'] = _money(num.parse('${wallet['balance']}') - amount);
      final total = num.parse('${invoice['total_amount']}');
      final paid = num.parse('${invoice['amount_paid']}') + amount;
      invoices[student] = _invoiceOf('${invoice['id']}', '${invoice['invoice_number']}', total: total, paid: paid);
    }
    if (loseNextAnswer) {
      loseNextAnswer = false;
      throw http.ClientException('connection lost after the server answered');
    }
    return ok({...payment, 'replayed': false}, status: 201);
  }
}
