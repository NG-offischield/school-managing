import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:school_core/school_core.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

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

const me = {
  'id': 'u1',
  'username': 'prof@ecole.test',
  'first_name': 'Jean',
  'last_name': 'Mbarga',
  'memberships': [
    {
      'id': 'm1',
      'school_code': 'E1',
      'school_name': 'École Test',
      'status': 'ACTIVE',
      'is_primary_school': true,
      'roles': ['TEACHER'],
    },
  ],
};

/// Minimal fake of the auth endpoints, with token rotation.
class FakeAuthServer {
  final requests = <http.Request>[];
  int issued = 0;
  final valid = <String>{};
  String? access;
  bool suspended = false;
  Map<String, dynamic> identity = me;

  Map<String, dynamic> _tokens() {
    issued++;
    access = 'acc-$issued';
    final refresh = 'ref-$issued';
    valid.add(refresh);
    return {'access_token': access, 'refresh_token': refresh, 'access_expires_in': 900, 'session_id': 's1'};
  }

  Future<http.Response> handle(http.Request request) async {
    requests.add(request);
    final path = request.url.path.replaceFirst('/api/v1/', '');
    final body = request.body.isEmpty ? <String, dynamic>{} : (jsonDecode(request.body) as Map).cast<String, dynamic>();
    switch (path) {
      case 'auth/login/':
        if (suspended || body['password'] != 'Bon-Mot-De-Passe-2026') return fail(401, 'INVALID_CREDENTIALS');
        return ok(_tokens());
      case 'auth/refresh/':
        if (!valid.remove(body['refresh_token'])) return fail(401, 'INVALID_REFRESH_TOKEN');
        return ok(_tokens());
      case 'auth/logout/':
        valid.clear();
        return ok(null);
      case 'auth/activation/check/':
        return body['code'] == 'GOOD-CODE'
            ? ok({
                'first_name': 'Jean',
                'school': 'École Test',
                'login': 'prof@ecole.test',
                'expires_at': '2026-10-08T10:00:00Z',
              })
            : fail(400, 'INVALID_ACTIVATION_CODE');
      case 'auth/activation/complete/':
        if (body['code'] != 'GOOD-CODE') return fail(400, 'INVALID_ACTIVATION_CODE');
        if ('${body['password']}'.length < 10) {
          return fail(
            400,
            'VALIDATION_ERROR',
            details: {
              'password': ['Ce mot de passe est trop court.'],
            },
          );
        }
        return ok({'login': 'prof@ecole.test'});
    }
    if (request.headers['Authorization'] != 'Bearer $access') return fail(401, 'INVALID_ACCESS_TOKEN');
    if (path == 'auth/me/') return ok(identity);
    if (path == 'files/report.pdf') {
      return http.Response.bytes(utf8.encode('%PDF-1.4'), 200, headers: {'content-type': 'application/pdf'});
    }
    if (path == 'files/other.pdf') return fail(403, 'PERMISSION_DENIED');
    if (path == 'things/') {
      return ok(
        [
          {'id': 1},
        ],
        meta: {'count': 1, 'next': null},
      );
    }
    return fail(404, 'NOT_FOUND');
  }
}

void main() {
  late FakeAuthServer server;
  late ApiClient api;
  late MemoryTokenStore store;
  late AuthService auth;

  setUp(() {
    server = FakeAuthServer();
    api = ApiClient(baseUrl: 'http://h/api/v1/', client: MockClient(server.handle));
    store = MemoryTokenStore();
    auth = AuthService(api, store, requiredRole: 'TEACHER');
  });

  group('ApiClient', () {
    test('unwraps the envelope and maps errors', () async {
      api.accessToken = 'x';
      final error = await caught(api.get('auth/me/'));
      expect(error, isA<UnauthorizedException>());
      final missing = ApiClient(
        baseUrl: 'http://h/api/v1/',
        client: MockClient((_) async => fail(409, 'CONFLICT', details: {'rule': 'checkin_already_verified'})),
      )..accessToken = 'x';
      final conflict = await caught(missing.post('x/')) as ConflictException;
      expect(conflict.rule, 'checkin_already_verified');
      expect(conflict.userMessage, startsWith('Cette séance a déjà été vérifiée'));
    });

    test('offline is a NetworkException with a clear message', () async {
      final offline = ApiClient(
        baseUrl: 'http://h/api/v1/',
        client: MockClient((_) async => throw http.ClientException('down')),
      )..accessToken = 'x';
      final error = await caught(offline.get('things/')) as NetworkException;
      expect(error.userMessage, contains('Connexion au serveur impossible'));
    });
  });

  group('AuthService', () {
    test('login keeps ONLY the refresh token; the password is never stored', () async {
      await auth.login('prof@ecole.test', 'Bon-Mot-De-Passe-2026');
      expect(auth.status, AuthStatus.signedIn);
      expect(auth.identity!.fullName, 'Jean Mbarga');
      expect(store.refreshToken, 'ref-1');
      expect(api.accessToken, 'acc-1');
      final login = jsonDecode(server.requests.first.body) as Map;
      expect((login['device'] as Map)['platform'], 'ANDROID');
      expect(store.refreshToken, isNot(contains('Bon-Mot')));
    });

    test('an expired access token is refreshed once, transparently', () async {
      await auth.login('prof@ecole.test', 'Bon-Mot-De-Passe-2026');
      server.access = 'rotated-elsewhere'; // the current access token is no longer accepted
      server.valid.add('ref-1');
      final page = await api.page('things/'); // 401 -> refresh -> replay with the new token
      expect(page.count, 1);
      expect(server.requests.where((r) => r.url.path.endsWith('auth/refresh/')).length, 1);
    });

    test('refresh refused -> session expired, back to login', () async {
      await auth.login('prof@ecole.test', 'Bon-Mot-De-Passe-2026');
      server.valid.clear();
      server.access = 'other';
      await expectLater(api.get('things/'), throwsA(isA<UnauthorizedException>()));
      expect(auth.status, AuthStatus.signedOut);
      expect(auth.notice, contains('session a expiré'));
      expect(store.refreshToken, isNull);
    });

    test('restore resumes a remembered session; logout closes it', () async {
      await auth.login('prof@ecole.test', 'Bon-Mot-De-Passe-2026');
      final again = AuthService(api, store, requiredRole: 'TEACHER');
      await again.restore();
      expect(again.status, AuthStatus.signedIn);
      await again.logout();
      expect(again.status, AuthStatus.signedOut);
      expect(store.refreshToken, isNull);
      expect(api.accessToken, isNull);
      final third = AuthService(api, store);
      await third.restore();
      expect(third.status, AuthStatus.signedOut);
    });

    test('suspended account: login refused with an explicit message', () async {
      server.suspended = true;
      final error = await caught(auth.login('prof@ecole.test', 'Bon-Mot-De-Passe-2026'));
      expect((error as ApiException).userMessage, contains('compte suspendu'));
      expect(auth.status, isNot(AuthStatus.signedIn));
    });

    test('a non-teacher account cannot open the teacher app', () async {
      server.identity = {
        ...me,
        'memberships': [
          {
            'id': 'm1',
            'school_code': 'E1',
            'school_name': 'É',
            'status': 'ACTIVE',
            'is_primary_school': true,
            'roles': ['PARENT'],
          },
        ],
      };
      await expectLater(auth.login('prof@ecole.test', 'Bon-Mot-De-Passe-2026'), throwsA(isA<WrongRoleException>()));
      expect(store.refreshToken, isNull);
      expect(server.requests.any((r) => r.url.path.endsWith('auth/logout/')), isTrue);
    });

    test('activation: check, weak password refused, completion; codes never stored', () async {
      final preview = await auth.checkActivation(' GOOD-CODE ');
      expect(preview.login, 'prof@ecole.test');
      final bad = await caught(auth.checkActivation('WRONG')) as ApiException;
      expect(bad.userMessage, contains('invalide, expiré ou déjà utilisé'));
      final weak = await caught(auth.completeActivation('GOOD-CODE', 'court')) as ApiException;
      expect(weak.fieldErrors['password'], ['Ce mot de passe est trop court.']);
      expect(await auth.completeActivation('GOOD-CODE', 'Bon-Mot-De-Passe-2026'), 'prof@ecole.test');
      expect(store.refreshToken, isNull); // activation does not log in: the normal login follows
    });
  });

  group('Parent building blocks (ADR 0026)', () {
    test('PDF download: bytes after the permission check, refresh on 401, errors typed', () async {
      await auth.login('prof@ecole.test', 'Bon-Mot-De-Passe-2026');
      expect(utf8.decode(await api.download('files/report.pdf')), '%PDF-1.4');
      expect(await caught(api.download('files/other.pdf')), isA<ForbiddenException>());
      server.access = 'rotated'; // access token refused once -> one refresh, then replay
      expect(utf8.decode(await api.download('files/report.pdf')), '%PDF-1.4');
    });

    test('a PENDING membership is kept only by apps that allow it, and reloads once approved', () async {
      final pending = {
        ...me,
        'memberships': [
          {
            'id': 'm1',
            'school_code': 'E1',
            'school_name': 'École Test',
            'status': 'PENDING',
            'is_primary_school': true,
            'roles': <String>[],
          },
        ],
      };
      server.identity = pending;
      final parentAuth = AuthService(api, store, requiredRole: 'PARENT', allowPending: true);
      await parentAuth.login('prof@ecole.test', 'Bon-Mot-De-Passe-2026');
      expect(parentAuth.status, AuthStatus.pending);
      expect(store.refreshToken, isNotNull); // the session is kept
      expect(await caught(auth.login('prof@ecole.test', 'Bon-Mot-De-Passe-2026')), isA<ForbiddenException>());
      expect(auth.status, isNot(AuthStatus.signedIn)); // default: refused

      server.identity = {
        ...me,
        'memberships': [
          {
            ...(me['memberships'] as List).first as Map,
            'roles': ['PARENT'],
          },
        ],
      };
      await parentAuth.login('prof@ecole.test', 'Bon-Mot-De-Passe-2026');
      await parentAuth.reloadIdentity();
      expect(parentAuth.status, AuthStatus.signedIn);
    });

    test('money keeps the narrow no-break space and never uses doubles', () {
      expect(formatMoney('1500000.00'), '1 500 000 XAF');
      expect(formatMoney('-2500.50', 'EUR'), '−2 500,50 EUR');
    });
  });

  group('RealtimeClient', () {
    test('auth, resync, pushes, reconnection, revocation', () async {
      final channels = <FakeChannel>[];
      final refreshes = <bool>[];
      api.accessToken = 'acc-1';
      final client = RealtimeClient(
        api,
        socketUri('http://h:8000/api/v1/'),
        channelFactory: (uri, headers) {
          expect(uri.toString(), 'ws://h:8000/ws/v1/realtime/');
          expect(headers['Authorization'], 'Bearer acc-1');
          return channels.add(FakeChannel()) as dynamic ?? channels.last;
        },
        refresh: () async {
          refreshes.add(true);
          return refreshes.length == 1;
        },
      );
      final notifications = <Map>[];
      final unread = <int>[];
      final expired = <bool>[];
      client.notifications.listen(notifications.add);
      client.unreadNotifications.listen(unread.add);
      client.sessionExpired.listen((_) => expired.add(true));
      client.watch('c1');
      client.start();
      channels.last.push({'type': 'auth.ok', 'unread_notifications': 2});
      await pump();
      expect(client.state, RealtimeState.online);
      expect(channels.last.sent.take(2), [
        {'type': 'sync'},
        {'type': 'subscribe', 'conversation': 'c1'},
      ]);
      channels.last.push({
        'type': 'notification',
        'data': {'id': 'n1', 'created_at': '2026-10-05T10:00:00Z'},
      });
      await pump();
      expect(notifications.single['id'], 'n1');
      expect(unread, [2]);
      // Revoked token: one refresh, then reconnection that resyncs since the last notification.
      channels.last.closeWith(unauthorizedClose);
      await pump();
      expect(channels.length, 2);
      channels.last.push({'type': 'auth.ok', 'unread_notifications': 3});
      await pump();
      expect(channels.last.sent.first, {'type': 'sync', 'since': '2026-10-05T10:00:00Z'});
      // Revoked again and the refresh fails: session expired.
      channels.last.closeWith(unauthorizedClose);
      await pump();
      expect(client.state, RealtimeState.expired);
      expect(expired, [true]);
      await client.dispose();
    });
  });
}

Future<void> pump() => Future<void>.delayed(Duration.zero);

Future<Object?> caught(Future<Object?> future) async {
  try {
    await future;
    return null;
  } on Object catch (error) {
    return error;
  }
}

class FakeChannel implements WebSocketChannel {
  final incoming = StreamController<dynamic>();
  final sent = <Map>[];
  int? code;
  late final _FakeSink _sink = _FakeSink(this);

  void push(Map frame) => incoming.add(jsonEncode(frame));

  void closeWith(int closeCode) {
    code = closeCode;
    incoming.close();
  }

  @override
  Stream get stream => incoming.stream;

  @override
  WebSocketSink get sink => _sink;

  @override
  int? get closeCode => code;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _FakeSink implements WebSocketSink {
  _FakeSink(this.channel);

  final FakeChannel channel;

  @override
  void add(dynamic data) => channel.sent.add(jsonDecode('$data') as Map);

  @override
  Future close([int? closeCode, String? closeReason]) async {}

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}
