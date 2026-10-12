/// In-memory fake of the Django API for the guardian widget tests: the
/// CONTRACT the app relies on — envelope, tokens, activation, MY scans only
/// (filtered on the caller), the scan answer decided by the server (with
/// the solvency only because the caller is a guardian), communication.
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
  FakePerson(this.key, this.first, this.last, this.email, {this.roles = const ['GUARDIAN']});

  final String key;
  final String first;
  final String last;
  final String email;
  final List<String> roles;
  String password = 'Portail-Kribi-2026!';

  String get name => '$first $last';
}

/// Card QR tokens, in the real format (secrets.token_urlsafe(32)).
const qrLea = 'LeaMbarga_7dK2pQ9vX4mZ8rT1wY6bN3cF5hJ0aSx';
const qrRevoked = 'OldCard-8sJ3kL0pQ2wE4rT6yU8iO1aS3dF5gH7jK';
const qrOtherSchool = 'OtherSchool_2xC4vB6nM8qW0eR2tY4uI6oP8aSd';

class FakeApi {
  FakeApi() {
    scans = [
      _scan('sc1', a, 'Léa Mbarga', 'ACCEPTED', 7),
      _scan('sc2', a, null, 'UNKNOWN_TOKEN', 7),
      _scan('sc3', b, 'Tom Ndiaye', 'ACCEPTED', 7), // B's: never shown to A
    ];
  }

  final a = FakePerson('ga', 'Moussa', 'Bello', 'moussa@ecole.test');
  final b = FakePerson('gb', 'Ali', 'Kamga', 'ali@ecole.test');
  final parent = FakePerson('pa', 'Awa', 'Parent', 'awa@parents.test', roles: const ['PARENT']);
  late List<Map<String, dynamic>> scans;
  final conversations = <Map<String, dynamic>>[];
  final complaints = <Map<String, dynamic>>[];
  final requests = <http.Request>[];
  final tokens = <String, FakePerson>{};
  final refreshes = <String, FakePerson>{};
  final suspended = <String>{};
  String activationCode = 'K7Q2-M9XA-4TZP-QH3W-B8NC';
  bool activationUsed = false;
  bool offline = false;
  int scanCalls = 0;
  int issued = 0;

  List<FakePerson> get people => [a, b, parent];

  String _at(int hour) => '${_day.format(DateTime.now())}T${hour.toString().padLeft(2, '0')}:05:00+01:00';

  Map<String, dynamic> _scan(String id, FakePerson by, String? student, String result, int hour) => {
    'id': id,
    'scanned_by': 'm-${by.key}',
    'student_name': student,
    'result': result,
    'scanned_at': _at(hour),
  };

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

  Future<http.Response> call(http.Request request) async {
    requests.add(request);
    if (offline) throw http.ClientException('offline');
    final path = request.url.path.replaceFirst('/api/v1/', '');
    final params = request.url.queryParameters;
    final body = request.body.isEmpty ? <String, dynamic>{} : (jsonDecode(request.body) as Map).cast<String, dynamic>();
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
      case 'auth/activation/check/':
        if (activationUsed || body['code'] != activationCode) return fail(400, 'INVALID_ACTIVATION_CODE');
        return ok({
          'first_name': a.first,
          'school': 'École Test',
          'login': a.email,
          'expires_at': '2026-12-01T10:00:00Z',
        });
      case 'auth/activation/complete/':
        if (activationUsed || body['code'] != activationCode) return fail(400, 'INVALID_ACTIVATION_CODE');
        if ('${body['password']}'.length < 10) {
          return fail(
            400,
            'VALIDATION_ERROR',
            details: {
              'password': ['Ce mot de passe est trop court.'],
            },
          );
        }
        activationUsed = true;
        a.password = '${body['password']}';
        return ok({'login': a.email});
    }
    final who = tokens[request.headers['Authorization']?.replaceFirst('Bearer ', '')];
    if (who == null) return fail(401, 'INVALID_ACCESS_TOKEN');
    if (path == 'auth/logout/') {
      tokens.removeWhere((_, p) => p == who);
      return ok(null);
    }
    // Self-service profile (accounts/profile_api.py): the SERVER decides the editable fields.
    if (path == 'auth/me/profile/') {
      final parentRole = who.roles.contains('PARENT');
      final employee = who.roles.contains('TEACHER') || who.roles.contains('STAFF');
      return ok({
        'first_name': who.first,
        'last_name': who.last,
        'email': who.email,
        'username': who.email,
        'phone': '',
        'has_photo': false,
        'school_name': 'École Test',
        'roles': who.roles,
        'parent': parentRole
            ? {'occupation': '', 'address': '', 'emergency_phone': '', 'preferred_language': 'fr'}
            : null,
        'employee': employee ? {'address': ''} : null,
        'editable': [
          'phone',
          if (parentRole) ...['occupation', 'address', 'emergency_phone', 'preferred_language'],
          if (employee) 'address',
        ],
        'languages': parentRole ? {'fr': 'Français', 'en': 'Anglais'} : {},
      });
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
            'status': 'ACTIVE',
            'is_primary_school': true,
            'roles': who.roles,
          },
        ],
      });
    }
    if (path == 'guardians/scans/') {
      // Server-side: the caller's own scans only.
      final rows = scans
          .where((s) => s['scanned_by'] == 'm-${who.key}' && '${s['scanned_at']}'.startsWith('${params['date']}'))
          .toList();
      return page(rows);
    }
    if (path == 'qr/scans/') {
      if (!who.roles.contains('GUARDIAN')) return fail(403, 'PERMISSION_DENIED');
      scanCalls++;
      final known = body['token'] == qrLea;
      // The server decides: a revoked card, another school's card (= unknown here), anything else.
      final refused = body['token'] == qrRevoked ? 'REVOKED_TOKEN' : 'UNKNOWN_TOKEN';
      final row = _scan('sc${scans.length + 1}', who, known ? 'Léa Mbarga' : null, known ? 'ACCEPTED' : refused, 8);
      scans.add(row);
      return ok({
        'scan_id': row['id'],
        'result': row['result'],
        'scanned_at': row['scanned_at'],
        'student': known ? {'id': 's1', 'name': 'Léa Mbarga', 'class': '6e A'} : null,
        'attendance': known ? {'status': 'LATE', 'arrival_time': '08:05:00', 'late_minutes': 35} : null,
        'solvency': known ? 'OVERDUE' : null, // guardians may see it (UP_TO_DATE / OVERDUE only)
      }, status: 201);
    }
    if (path == 'school-breaks/') {
      final next = DateTime.now().add(const Duration(days: 10));
      return page([
        {
          'id': 'b1',
          'name': 'Vacances de Noël',
          'break_type': 'HOLIDAY',
          'start_datetime': '${_day.format(next)}T00:00:00+01:00',
          'end_datetime': '${_day.format(next.add(const Duration(days: 14)))}T23:59:00+01:00',
        },
        {
          'id': 'b0',
          'name': 'Fête passée',
          'break_type': 'PUBLIC_HOLIDAY',
          'start_datetime': '2020-01-01T00:00:00+01:00',
          'end_datetime': '2020-01-01T23:59:00+01:00',
        },
      ]);
    }
    if (path == 'notifications/') {
      return page([
        if (who == a)
          {
            'id': 'n1',
            'notification_type': 'ANNOUNCEMENT',
            'severity': 'INFO',
            'title': 'Portail fermé à 18 h',
            'message': 'Travaux.',
            'is_read': false,
            'created_at': _at(6),
          },
      ]);
    }
    if (path == 'notifications/unread-count/') return ok({'unread': who == a ? 1 : 0});
    if (path.startsWith('notifications/') && path.endsWith('/read/')) return ok({'is_read': true});
    if (path == 'conversations/') {
      if (request.method == 'POST') {
        final row = {
          'id': 'conv${conversations.length + 1}',
          'conversation_type': body['conversation_type'],
          'title': body['title'] ?? '',
          'participants': [
            {'member': 'm-${who.key}', 'name': who.name},
          ],
          'unread_count': 0,
          'last_message_at': _at(9),
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
          'created_at': _at(9),
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
          'created_at': _at(9),
        };
        complaints.add(row);
        return ok(row, status: 201);
      }
      return page(complaints);
    }
    return fail(404, 'NOT_FOUND');
  }
}
