/// Server chosen at runtime (ServerHost): priority saved > build > none,
/// validation, the real health check, and a switch that leaves the old
/// school entirely (session, tokens, data, WebSocket) before using the new one.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

const a = 'http://192.168.1.10:8000';
const b = 'http://10.0.0.20:8000';

http.Response _json(Object body, [int status = 200]) =>
    http.Response.bytes(utf8.encode(jsonEncode(body)), status, headers: {'content-type': 'application/json'});

/// Two schools on two servers (one per host). The old one can vanish (network change).
class TwoSchools {
  final requests = <String>[];
  final down = <String>{};

  Future<http.Response> call(http.Request request) async {
    final server = '${request.url.scheme}://${request.url.host}:${request.url.port}';
    requests.add('${request.method} $server${request.url.path}');
    if (down.contains(server)) throw const SocketException('No route to host');
    final school = server == a ? 'École A' : (server == b ? 'École B' : null);
    if (school == null) throw const SocketException('Connection refused');
    switch (request.url.path) {
      case '/api/v1/health/':
        return _json({
          'success': true,
          'data': {'status': 'ok'},
        });
      case '/api/v1/school/':
        return _json({
          'success': true,
          'data': {'name': school},
        });
      case '/api/v1/auth/logout/':
        return _json({'success': true, 'data': null});
    }
    return _json({
      'success': false,
      'error': {'code': 'NOT_FOUND', 'message': 'x'},
    }, 404);
  }
}

class RecordingChannel implements WebSocketChannel {
  RecordingChannel(this.uri);

  final Uri uri;
  final incoming = StreamController<dynamic>();
  bool closed = false;
  late final _sink = _Sink(this);

  @override
  Stream get stream => incoming.stream;

  @override
  WebSocketSink get sink => _sink;

  @override
  int? get closeCode => null;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _Sink implements WebSocketSink {
  _Sink(this.channel);

  final RecordingChannel channel;

  @override
  void add(dynamic data) {}

  @override
  Future close([int? closeCode, String? closeReason]) async => channel.closed = true;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

/// A minimal "app" for one server: reads its school, opens the live connection.
class SchoolHome extends StatefulWidget {
  const SchoolHome({super.key, required this.api, required this.live});

  final ApiClient api;
  final RealtimeClient live;

  @override
  State<SchoolHome> createState() => _SchoolHomeState();
}

class _SchoolHomeState extends State<SchoolHome> {
  String? school;

  @override
  void initState() {
    super.initState();
    widget.live.start();
    widget.api.get('school/').then((data) {
      if (mounted) setState(() => school = (data as Map)['name'] as String);
    });
  }

  @override
  void dispose() {
    widget.live.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: ListView(
      children: [
        Text(school ?? '…', key: const Key('school')),
        const ServerSettingsTile(),
      ],
    ),
  );
}

class World {
  World({String? saved, this.build = ''}) : store = MemoryEndpointStore(saved);

  final MemoryEndpointStore store;
  final String build;
  final server = TwoSchools();
  final channels = <RecordingChannel>[];
  final sessions = <AppConfig>[];
  final tokens = <MemoryTokenStore>[];
  int left = 0;

  ServerSession session(AppConfig config) {
    sessions.add(config);
    final api = ApiClient(baseUrl: config.apiUrl, client: MockClient(server.call))
      ..accessToken = 'acc-${config.api.host}';
    final store = MemoryTokenStore()..refreshToken = 'ref-${config.api.host}';
    tokens.add(store);
    final auth = AuthService(api, store);
    final live = RealtimeClient(
      api,
      config.socket,
      channelFactory: (uri, headers) {
        final channel = RecordingChannel(uri);
        channels.add(channel);
        return channel;
      },
    );
    return ServerSession(
      app: MaterialApp(
        home: ChangeNotifierProvider<AuthService>.value(
          value: auth,
          child: SchoolHome(api: api, live: live),
        ),
      ),
      leave: () async {
        left++;
        await auth.leaveServer(serverTimeout: const Duration(milliseconds: 200));
      },
    );
  }

  Widget host() => ServerHost(
    store: store,
    session: session,
    buildApiUrl: build,
    httpClient: MockClient(server.call),
    release: false,
  );
}

Future<void> switchTo(WidgetTester tester, String address, {bool test = true}) async {
  await tester.tap(find.byKey(const Key('profile.server')));
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(const Key('server.address')), address);
  if (test) {
    await tester.tap(find.byKey(const Key('server.test')));
    await tester.pumpAndSettle();
  }
  await tester.tap(find.byKey(const Key('server.save')));
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const lanChannel = MethodChannel('school_core/local_network');
  // Android 10–16 by default: no local-network permission to ask (the Android 17 test overrides it).
  setUp(
    () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(
      lanChannel,
      (call) async => {'sdkInt': 34, 'required': false, 'granted': true, 'canAsk': false},
    ),
  );
  tearDown(
    () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(lanChannel, null),
  );

  group('AppConfig.server: one address, REST + WebSocket built from it', () {
    test('http -> ws, https -> wss, port kept, the backend\'s own paths', () {
      final lan = AppConfig.server('http://192.168.1.102:8000', release: false);
      expect(lan.apiUrl, 'http://192.168.1.102:8000/api/v1/');
      expect(lan.socket.toString(), 'ws://192.168.1.102:8000/ws/v1/realtime/');
      expect(lan.serverAddress, 'http://192.168.1.102:8000');
      final tls = AppConfig.server('https://ecole.example.org', release: true);
      expect(tls.apiUrl, 'https://ecole.example.org/api/v1/');
      expect(tls.socket.toString(), 'wss://ecole.example.org/ws/v1/realtime/');
    });

    test('same result as the build-time API_URL of lan.json (paths unchanged)', () {
      final fromServer = AppConfig.server('192.168.1.102:8000/api/v1/', release: false);
      final fromBuild = AppConfig.parse(
        apiUrl: 'http://192.168.1.102:8000/api/v1/',
        wsUrl: 'ws://192.168.1.102:8000/ws/v1/realtime/',
        release: false,
      );
      expect(fromServer.apiUrl, fromBuild.apiUrl);
      expect(fromServer.socket, fromBuild.socket);
    });

    test('malformed or dangerous addresses are refused, with a reason', () {
      for (final bad in [
        '',
        'ftp://192.168.1.10',
        'http://',
        'http://user:secret@192.168.1.10:8000',
        'http://192.168.1.10:8000/admin/',
        'http://192.168.1.10:8000/?next=x',
        'http://192.168.1.10:8000#x',
        'http://8.8.8.8:8000', // clear text towards the Internet
      ]) {
        expect(() => AppConfig.server(bad, release: false), throwsA(isA<AppConfigException>()), reason: bad);
      }
      expect(() => AppConfig.server('http://192.168.1.10:8000', release: true), throwsA(isA<AppConfigException>()));
    });
  });

  group('priority: saved > build (dart-define) > none', () {
    test('the saved address wins over the build one', () {
      final r = resolveServer(saved: b, buildApiUrl: '$a/api/v1/', release: false);
      expect(r.source, ServerSource.saved);
      expect(r.config!.serverAddress, b);
      expect(r.build!.serverAddress, a);
    });

    test('nothing saved: the build value; nothing at all: ask the user', () {
      expect(resolveServer(buildApiUrl: '$a/api/v1/', release: false).config!.serverAddress, a);
      final none = resolveServer(release: false);
      expect(none.config, isNull);
      expect(none.source, ServerSource.none);
    });

    test('an invalid saved address is ignored and explained', () {
      final r = resolveServer(saved: 'http://u:p@192.168.1.10', buildApiUrl: '$a/api/v1/', release: false);
      expect(r.source, ServerSource.build);
      expect(r.warning, contains('ignorée'));
    });
  });

  group('checkServer: the real health endpoint, no simulated success', () {
    final config = AppConfig.server(a, release: false);

    Future<ServerCheck> check(Future<http.Response> Function(http.Request) handler) =>
        checkServer(config, client: MockClient(handler), timeout: const Duration(milliseconds: 200));

    test('GET /api/v1/health/ answering ok = reachable', () async {
      late Uri asked;
      final result = await check((r) async {
        asked = r.url;
        return _json({
          'success': true,
          'data': {'status': 'ok'},
        });
      });
      expect(asked.toString(), '$a/api/v1/health/');
      expect(result.kind, ServerCheckKind.ok);
    });

    test('unreachable, timeout, refused host, unexpected answers are told apart', () async {
      expect((await check((_) async => throw const SocketException('refused'))).kind, ServerCheckKind.unreachable);
      expect(
        (await check((_) => Completer<http.Response>().future)).kind, // never answers
        ServerCheckKind.timeout,
      );
      final host = await check((_) async => http.Response('Bad Request', 400));
      expect(host.kind, ServerCheckKind.unexpected);
      expect(host.message, contains('configure_lan.ps1'));
      expect((await check((_) async => http.Response('<html>box</html>', 200))).kind, ServerCheckKind.unexpected);
      expect((await check((_) async => _json({'success': true}, 503))).status, 503);
    });
  });

  group('ServerHost', () {
    testWidgets('a saved address is used instead of the build one, without rebuild', (tester) async {
      final w = World(saved: b, build: '$a/api/v1/');
      await tester.pumpWidget(w.host());
      await tester.pumpAndSettle();
      expect(w.sessions.single.serverAddress, b);
      expect(find.text('École B'), findsOneWidget);
    });

    testWidgets('no address at all: the settings screen opens first', (tester) async {
      final w = World();
      await tester.pumpWidget(w.host());
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('server.address')), findsOneWidget);
      expect(w.sessions, isEmpty);
      await tester.enterText(find.byKey(const Key('server.address')), a);
      await tester.tap(find.byKey(const Key('server.test')));
      await tester.pumpAndSettle();
      expect(find.textContaining('Serveur joignable'), findsOneWidget);
      await tester.tap(find.byKey(const Key('server.save')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('server.confirm.ok')));
      await tester.pumpAndSettle();
      expect(find.text('École A'), findsOneWidget);
      expect(w.store.address, a);
    });

    testWidgets('switching server: confirmed, old session left, new endpoint, no mixing', (tester) async {
      final w = World(build: '$a/api/v1/');
      await tester.pumpWidget(w.host());
      await tester.pumpAndSettle();
      expect(find.text('École A'), findsOneWidget);
      final oldSocket = w.channels.single;
      expect(oldSocket.uri.toString(), 'ws://192.168.1.10:8000/ws/v1/realtime/');
      w.server.down.add(a); // the PC moved to another network: the old address is gone

      await switchTo(tester, b);
      expect(find.text('Nouveau serveur : $b'), findsOneWidget);
      expect(w.left, 0); // nothing done before the confirmation
      await tester.tap(find.byKey(const Key('server.confirm.ok')));
      await tester.pumpAndSettle();

      expect(w.left, 1);
      expect(w.tokens.first.refreshToken, isNull); // old session dropped although the old server is unreachable
      expect(oldSocket.closed, isTrue); // old WebSocket closed
      expect(w.channels.last.uri.toString(), 'ws://10.0.0.20:8000/ws/v1/realtime/'); // reconnected on the new one
      expect(find.text('École A'), findsNothing); // nothing of the old school
      expect(find.text('École B'), findsOneWidget);
      expect(w.store.address, b);
      expect(find.text(b), findsOneWidget); // the active address is shown
      expect(w.server.requests.where((r) => r.contains('10.0.0.20') && r.contains('/school/')), hasLength(1));
    });

    testWidgets('cancelling the confirmation changes nothing', (tester) async {
      final w = World(build: '$a/api/v1/');
      await tester.pumpWidget(w.host());
      await tester.pumpAndSettle();
      await switchTo(tester, b, test: false);
      expect(find.textContaining('pas été vérifiée'), findsOneWidget); // not tested: said so
      await tester.tap(find.text('Annuler'));
      await tester.pumpAndSettle();
      expect(w.left, 0);
      expect(w.store.address, isNull);
      expect(w.sessions, hasLength(1));
    });

    testWidgets('same address saved again: same session kept, nothing cleared', (tester) async {
      final w = World(saved: a);
      await tester.pumpWidget(w.host());
      await tester.pumpAndSettle();
      await switchTo(tester, '$a/', test: false);
      expect(find.byKey(const Key('server.confirm.ok')), findsNothing);
      expect(w.left, 0);
      expect(w.sessions, hasLength(1));
      expect(w.channels.single.closed, isFalse);
      expect(find.text('École A'), findsOneWidget);
    });

    testWidgets('a malformed address is explained and never saved', (tester) async {
      final w = World(saved: a);
      await tester.pumpWidget(w.host());
      await tester.pumpAndSettle();
      await switchTo(tester, 'http://admin:pw@10.0.0.20:8000', test: false);
      expect(find.textContaining('ni identifiant ni mot de passe'), findsOneWidget);
      expect(w.store.address, a);
      expect(w.left, 0);
    });

    testWidgets('back to the installation address forgets the saved one', (tester) async {
      final w = World(saved: b, build: '$a/api/v1/');
      await tester.pumpWidget(w.host());
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('profile.server')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('server.reset')));
      await tester.pumpAndSettle();
      expect(w.store.address, isNull);
      expect(w.left, 1);
      expect(find.text('École A'), findsOneWidget);
    });

    testWidgets('Android 17 refusal of the local network is reported, not a fake failure', (tester) async {
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        lanChannel,
        (call) async => {'sdkInt': 37, 'required': true, 'granted': false, 'canAsk': false},
      );
      final w = World();
      await tester.pumpWidget(w.host());
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('server.address')), a);
      await tester.tap(find.byKey(const Key('server.test')));
      await tester.pumpAndSettle();
      expect(find.textContaining('réseau local'), findsWidgets);
      expect(w.server.requests, isEmpty); // nothing sent while Android blocks it
    });
  });

  testWidgets('sign-in screen: the server is shown and can be changed there', (tester) async {
    final store = MemoryEndpointStore(a);
    final server = TwoSchools();
    await tester.pumpWidget(
      ServerHost(
        store: store,
        release: false,
        httpClient: MockClient(server.call),
        session: (config) {
          final auth = AuthService(
            ApiClient(baseUrl: config.apiUrl, client: MockClient(server.call)),
            MemoryTokenStore(),
          )..status = AuthStatus.signedOut;
          return ServerSession(
            app: MaterialApp(
              home: ChangeNotifierProvider<AuthService>.value(
                value: auth,
                child: SignInScreen(subtitle: 'Test', roleLabel: 'test', alternative: SignInAlternative.activation()),
              ),
            ),
            leave: auth.leaveServer,
          );
        },
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Serveur : 192.168.1.10:8000'), findsOneWidget);
    await tester.ensureVisible(find.byKey(const Key('login.server.change')));
    await tester.tap(find.byKey(const Key('login.server.change')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('server.address')), findsOneWidget);
    await tester.enterText(find.byKey(const Key('server.address')), b);
    await tester.tap(find.byKey(const Key('server.save')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('server.confirm.ok')));
    await tester.pumpAndSettle();
    expect(find.text('Serveur : 10.0.0.20:8000'), findsOneWidget); // back on the sign-in, new server
  });
}
