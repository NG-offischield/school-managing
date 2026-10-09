/// In-memory fake of the Django API for the widget tests. It reproduces the
/// CONTRACT the app relies on (envelope, tokens, visibility per teacher,
/// 401 / 403 / 404 / 400 answers), not the backend's logic.
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

class FakeTeacher {
  FakeTeacher(this.key, this.first, this.last, this.email, {this.roles = const ['TEACHER']});

  final String key;
  final String first;
  final String last;
  final String email;
  final List<String> roles;
  String password = 'Craie-Tableau-2026!';

  String get name => '$first $last';
}

class FakeApi {
  FakeApi() {
    final today = DateTime.now();
    String at(int dayOffset, int hour) =>
        '${_day.format(today.add(Duration(days: dayOffset)))}T${hour.toString().padLeft(2, '0')}:00:00+01:00';
    Map<String, dynamic> session(
      String id,
      FakeTeacher t,
      String subject,
      String klass,
      int day,
      int hour, {
      String status = 'SCHEDULED',
      FakeTeacher? planned,
    }) => {
      'id': id,
      'subject': {'id': 's-$subject', 'code': subject, 'name': subject == 'MATH' ? 'Mathématiques' : 'Français'},
      'school_class': {'id': 'c-$klass', 'name': klass},
      'teacher': {'id': t.key, 'name': t.name},
      'planned_teacher': {'id': (planned ?? t).key, 'name': (planned ?? t).name},
      'room': {'id': 'r1', 'code': 'R12', 'name': 'Salle 12'},
      'date': _day.format(today.add(Duration(days: day))),
      'scheduled_start': at(day, hour),
      'scheduled_end': at(day, hour + 2),
      'status': status,
      'is_substituted': planned != null,
      'is_moved': false,
    };
    sessions = [
      session('sa1', a, 'MATH', '6e A', 0, 0),
      session('sa2', a, 'MATH', '5e B', 0, 1), // earlier today
      session('sa3', a, 'MATH', '6e A', 2, 10, status: 'CANCELLED'),
      session('sa4', a, 'FR', '4e C', 1, 14, planned: b), // A replaces B
      session('sb1', b, 'FR', '4e C', 0, 9), // B's: never shown to A
      session('sb2', b, 'FR', '3e D', 1, 8),
    ];
    notifications = {
      a.key: [
        {
          'id': 'na1',
          'notification_type': 'SUBSTITUTION',
          'severity': 'INFO',
          'title': 'Remplacement demain',
          'message': 'Vous remplacez Marie Ngo.',
          'is_read': false,
          'created_at': at(0, 7),
        },
        {
          'id': 'na2',
          'notification_type': 'PAYROLL',
          'severity': 'INFO',
          'title': 'Paie validée',
          'message': 'Octobre.',
          'is_read': true,
          'created_at': at(-1, 7),
        },
      ],
      b.key: [
        {
          'id': 'nb1',
          'notification_type': 'MESSAGE',
          'severity': 'INFO',
          'title': 'Message pour Marie',
          'message': '…',
          'is_read': false,
          'created_at': at(0, 7),
        },
      ],
    };
  }

  final a = FakeTeacher('ta', 'Jean', 'Mbarga', 'jean@ecole.test');
  final b = FakeTeacher('tb', 'Marie', 'Ngo', 'marie@ecole.test');
  final parent = FakeTeacher('pa', 'Paul', 'Parent', 'parent@ecole.test', roles: const ['PARENT']);
  late List<Map<String, dynamic>> sessions;
  late Map<String, List<Map<String, dynamic>>> notifications;
  final requests = <http.Request>[];
  final tokens = <String, FakeTeacher>{}; // access -> who
  final refreshes = <String, FakeTeacher>{};
  final suspended = <String>{};
  final checkIns = <String, String>{};
  String activationCode = 'K7Q2-M9XA-4TZP-QH3W-B8NC';
  bool activationUsed = false;
  bool offline = false;
  int issued = 0;

  List<FakeTeacher> get people => [a, b, parent];

  Map<String, dynamic> _issue(FakeTeacher who) {
    issued++;
    tokens['acc-$issued'] = who;
    refreshes['ref-$issued'] = who;
    return {
      'access_token': 'acc-$issued',
      'refresh_token': 'ref-$issued',
      'access_expires_in': 900,
      'session_id': 's$issued',
    };
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
          'first_name': 'Jean',
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
              'password': ['Ce mot de passe est trop court. Il doit contenir au minimum 10 caractères.'],
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
            'school_name': 'École Test',
            'status': 'ACTIVE',
            'is_primary_school': true,
            'roles': who.roles,
          },
        ],
      });
    }
    // Server-side visibility: a teacher sees only sessions they teach or were planned on.
    bool mine(Map<String, dynamic> s) =>
        (s['teacher'] as Map)['id'] == who.key || (s['planned_teacher'] as Map)['id'] == who.key;
    if (path == 'teacher/sessions/') {
      final from = params['date_from']!, to = params['date_to']!;
      final rows = sessions
          .where((s) => mine(s) && '${s['date']}'.compareTo(from) >= 0 && '${s['date']}'.compareTo(to) <= 0)
          .toList();
      return ok(rows, meta: {'count': rows.length, 'next': null});
    }
    if (path.startsWith('sessions/')) {
      final row = sessions.where((s) => s['id'] == path.split('/')[1]).firstOrNull;
      return row == null || !mine(row) ? fail(404, 'NOT_FOUND') : ok(row);
    }
    if (path.startsWith('teacher/sessions/') && path.endsWith('/check-in/')) {
      final id = path.split('/')[2];
      final row = sessions.where((s) => s['id'] == id && (s['teacher'] as Map)['id'] == who.key).firstOrNull;
      if (row == null) return fail(404, 'NOT_FOUND');
      if (DateTime.parse('${row['scheduled_start']}'.substring(0, 19)).isAfter(DateTime.now())) {
        return fail(400, 'BUSINESS_RULE_VIOLATION', details: {'rule': 'session_not_started'});
      }
      checkIns[id] = '${body['status']}';
      return ok({'self_reported_status': body['status']}, status: 201);
    }
    if (path == 'planning/changes/') {
      final rows = params['session'] == 'sa4'
          ? [
              {'change_type': 'TEACHER_SUBSTITUTED', 'changed_at': '2026-10-04T10:00:00+01:00', 'reason': 'Absence'},
            ]
          : <Map>[];
      return ok(rows, meta: {'count': rows.length, 'next': null});
    }
    if (path == 'courses/') {
      final rows = who.key == 'ta'
          ? [
              {
                'id': 'k1',
                'class_name': '6e A',
                'subject_code': 'MATH',
                'coefficient': '4.00',
                'weekly_hours': '5.00',
                'active': true,
              },
              {
                'id': 'k2',
                'class_name': '5e B',
                'subject_code': 'MATH',
                'coefficient': '4.00',
                'weekly_hours': null,
                'active': true,
              },
            ]
          : [
              {
                'id': 'k3',
                'class_name': '4e C',
                'subject_code': 'FR',
                'coefficient': '3.00',
                'weekly_hours': '4.00',
                'active': true,
              },
            ];
      return ok(rows, meta: {'count': rows.length, 'next': null});
    }
    if (path == 'teacher/payroll/') {
      return ok({
        'payrolls': [],
        'live': {
          'kind': 'TEACHER',
          'programmed_amount': '45000.00',
          'earned_unpaid_amount': '15000.00',
          'paid_amount': '0.00',
          'sessions': {'scheduled': 9, 'validated': 3, 'paid': 0, 'missing_rate': 0},
        },
      });
    }
    final own = notifications[who.key] ?? [];
    if (path == 'notifications/') {
      final rows = params['is_read'] == 'false' ? own.where((n) => n['is_read'] != true).toList() : own;
      return ok(rows, meta: {'count': rows.length, 'next': null});
    }
    if (path == 'notifications/unread-count/') return ok({'unread': own.where((n) => n['is_read'] != true).length});
    if (path == 'notifications/read-all/') {
      for (final n in own) {
        n['is_read'] = true;
      }
      return ok({'marked': own.length});
    }
    if (path.startsWith('notifications/') && path.endsWith('/read/')) {
      final row = own.where((n) => n['id'] == path.split('/')[1]).firstOrNull;
      if (row == null) return fail(404, 'NOT_FOUND');
      row['is_read'] = true;
      return ok(row);
    }
    if (path == 'conversations/') {
      final rows = who.key == 'ta'
          ? [
              {
                'id': 'cv1',
                'conversation_type': 'PARENT_TEACHER',
                'title': 'Devoirs de Awa',
                'student': 's0',
                'participants': [
                  {'member': 'm-ta', 'name': a.name},
                  {'member': 'm-pa', 'name': parent.name},
                ],
                'unread_count': 1,
                'last_message_at': null,
              },
            ]
          : <Map>[];
      return ok(rows, meta: {'count': rows.length, 'next': null});
    }
    if (path == 'conversations/cv1/messages/' && who.key == 'ta') {
      final rows = [
        {
          'id': 'msg1',
          'conversation': 'cv1',
          'sender_name': parent.name,
          'body': 'Bonjour, une question sur les devoirs.',
          'created_at': '2026-10-04T18:00:00+01:00',
          'attachments': <Map>[],
        },
      ];
      return ok(rows, meta: {'count': 1, 'next': null});
    }
    if (path == 'conversations/cv1/read/' && who.key == 'ta') return ok({'read': true});
    if (path == 'complaints/') return ok(<Map>[], meta: {'count': 0, 'next': null});
    // Forum (EXISTING API): the server decides the spaces of the member.
    if (path == 'forum/spaces/') {
      return ok([
        {'id': 'sp1', 'name': 'Vie de l\x27école', 'announcements_only': false},
      ]);
    }
    if (path == 'forum/threads/') {
      return ok(
        [
          {
            'id': 'th1',
            'space': 'sp1',
            'title': 'Réunion de rentrée',
            'thread_type': 'ANNOUNCEMENT',
            'status': 'OPEN',
            'author_name': 'Direction',
            'created_at': '2026-10-08T08:00:00+01:00',
            'last_post_at': '2026-10-08T08:00:00+01:00',
          },
        ],
        meta: {'count': 1, 'next': null},
      );
    }
    return fail(404, 'NOT_FOUND');
  }
}
