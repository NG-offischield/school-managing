/// In-memory fake of the Django API for the parent widget tests. It
/// reproduces the CONTRACT the app relies on — envelope, tokens, a pending
/// membership, visibility limited to VERIFIED children (another child is a
/// 404), financial rights per link (403 without can_view_financial_data),
/// validated report cards only — not the backend's logic.
library;

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
      return ok({
        'student': id,
        'currency': 'XAF',
        'balance_due': '40000.00',
        'solvency': 'OVERDUE',
        'can_pay': row['can_pay'],
        'open_invoices': [_invoice()],
      });
    }
    if (path == 'finance/invoices/') {
      final row = link(params['student'] ?? '');
      return page(row != null && row['can_view_financial_data'] == true ? [_invoice()] : []);
    }
    if (path == 'finance/payments/') {
      return page(
        mineIds.contains(params['student'])
            ? [
                {
                  'id': 'pay1',
                  'payment_reference': 'PAY-0001',
                  'amount': '60000.00',
                  'currency': 'XAF',
                  'status': 'SUCCEEDED',
                  'completed_at': _at(-20, 9),
                },
              ]
            : [],
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
    if (path == 'report-cards/rc1/pdf/' || path == 'payments/pay1/receipt.pdf/') {
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

  Map<String, dynamic> _invoice() => {
    'id': 'inv1',
    'invoice_number': 'FAC-2026-0001',
    'status': 'PARTIALLY_PAID',
    'issue_date': '2026-09-01',
    'due_date': '2026-09-30',
    'total_amount': '100000.00',
    'amount_paid': '60000.00',
    'balance_due': '40000.00',
    'currency': 'XAF',
    'lines': [
      {'fee_type_code': 'TUITION', 'description': 'Scolarité', 'total': '100000.00'},
    ],
  };
}
