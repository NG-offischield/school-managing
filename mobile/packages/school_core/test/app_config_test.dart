import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:school_core/school_core.dart';

AppConfig parse(String api, {String ws = '', bool release = false}) =>
    AppConfig.parse(apiUrl: api, wsUrl: ws, release: release);

void main() {
  group('AppConfig (API_URL / WS_URL)', () {
    test('LAN address of the PC: REST + derived WebSocket on the same host', () {
      final config = parse('http://192.168.1.100:8000/api/v1');
      expect(config.apiUrl, 'http://192.168.1.100:8000/api/v1/');
      expect(config.socket.toString(), 'ws://192.168.1.100:8000/ws/v1/realtime/');
      expect(config.serverLabel, '192.168.1.100:8000');
    });

    test('explicit WS_URL on the same host', () {
      final config = parse('http://10.0.0.5:8000/api/v1/', ws: 'ws://10.0.0.5:8000/ws/v1/realtime/');
      expect(config.socket.toString(), 'ws://10.0.0.5:8000/ws/v1/realtime/');
    });

    test('missing address: explained, never a silent default', () {
      expect(() => parse(''), throwsA(isA<AppConfigException>()));
    });

    test('malformed addresses are refused', () {
      expect(() => parse('192.168.1.10:8000'), throwsA(isA<AppConfigException>()));
      expect(() => parse('ftp://192.168.1.10/api/v1/'), throwsA(isA<AppConfigException>()));
      expect(
        () => parse('http://192.168.1.10:8000/api/v1/', ws: 'http://192.168.1.10:8000/ws/'),
        throwsA(isA<AppConfigException>()),
      );
    });

    test('clear text only towards private addresses, loopback and the emulator', () {
      for (final host in [
        '192.168.0.12',
        '10.1.2.3',
        '172.16.0.1',
        '172.31.255.1',
        '127.0.0.1',
        '10.0.2.2',
        'localhost',
        'pc-ecole.local',
      ]) {
        expect(parse('http://$host:8000/api/v1/').api.host, host);
      }
      for (final host in ['8.8.8.8', '172.32.0.1', '172.15.0.1', '192.169.1.1', 'school.example.com']) {
        expect(() => parse('http://$host:8000/api/v1/'), throwsA(isA<AppConfigException>()), reason: host);
      }
    });

    test('https / wss accepted for any host', () {
      final config = parse('https://school.example.com/api/v1/');
      expect(config.socket.toString(), 'wss://school.example.com/ws/v1/realtime/');
    });

    test('release builds refuse clear text, even on the LAN', () {
      expect(() => parse('http://192.168.1.100:8000/api/v1/', release: true), throwsA(isA<AppConfigException>()));
      expect(parse('https://192.168.1.100/api/v1/', release: true).api.scheme, 'https');
    });

    test('the WebSocket never goes to another host (it carries the token)', () {
      expect(
        () => parse('http://192.168.1.100:8000/api/v1/', ws: 'ws://192.168.1.101:8000/ws/v1/realtime/'),
        throwsA(isA<AppConfigException>()),
      );
      expect(
        () => parse('https://school.example.com/api/v1/', ws: 'ws://school.example.com/ws/v1/realtime/'),
        throwsA(isA<AppConfigException>()),
      );
    });

    test('only a private non-loopback address needs the Android 17 permission', () {
      expect(needsLocalNetwork(parse('http://192.168.1.100:8000/api/v1/')), isTrue);
      expect(needsLocalNetwork(parse('http://10.0.2.2:8000/api/v1/')), isTrue);
      expect(needsLocalNetwork(parse('http://127.0.0.1:8000/api/v1/')), isFalse); // adb reverse
      expect(needsLocalNetwork(parse('http://localhost:8000/api/v1/')), isFalse);
      expect(needsLocalNetwork(parse('https://school.example.com/api/v1/')), isFalse);
    });
  });

  group('LocalNetworkGate (Android 17 ACCESS_LOCAL_NETWORK)', () {
    const channel = MethodChannel('school_core/local_network');
    final lan = parse('http://192.168.1.100:8000/api/v1/');
    late List<String> calls;

    void native(Map<String, Object?> Function(String method) answer) {
      calls = [];
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(channel, (call) async {
        calls.add(call.method);
        return call.method == 'openSettings' ? true : answer(call.method);
      });
    }

    Map<String, Object?> state({required int sdk, required bool granted, bool canAsk = false}) => {
      'sdkInt': sdk,
      'required': sdk >= 37,
      'granted': sdk < 37 || granted,
      'canAsk': canAsk,
    };

    tearDown(
      () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(channel, null),
    );

    Future<int> pump(WidgetTester tester, AppConfig config) async {
      var ready = 0;
      await tester.pumpWidget(
        LocalNetworkGate(
          config: config,
          onReady: () => ready++,
          child: const MaterialApp(home: Text('app')),
        ),
      );
      await tester.pumpAndSettle();
      return ready;
    }

    for (final sdk in [29, 31, 33, 34, 35, 36]) {
      testWidgets('API $sdk (Android 10–16): nothing asked, INTERNET is enough', (tester) async {
        native((_) => state(sdk: sdk, granted: false));
        expect(await pump(tester, lan), 1);
        expect(find.text('app'), findsOneWidget);
        expect(calls, ['status']);
      });
    }

    testWidgets('API 37, already granted: straight to the app', (tester) async {
      native((_) => state(sdk: 37, granted: true));
      expect(await pump(tester, lan), 1);
      expect(find.text('app'), findsOneWidget);
      expect(calls, ['status']);
    });

    testWidgets('API 37: asked once at start; granted -> app, session restored once', (tester) async {
      native((m) => state(sdk: 37, granted: m == 'request', canAsk: true));
      expect(await pump(tester, lan), 1);
      expect(calls, ['status', 'request']);
      expect(find.text('app'), findsOneWidget);
    });

    testWidgets('API 37: refused -> explanation, ask again -> granted', (tester) async {
      var allow = false;
      native((_) => state(sdk: 37, granted: allow, canAsk: true));
      expect(await pump(tester, lan), 0); // no request to the server before the permission
      expect(find.text('Accès au réseau local'), findsOneWidget);
      expect(find.text('app'), findsNothing);
      allow = true;
      await tester.tap(find.byKey(const Key('lan.ask')));
      await tester.pumpAndSettle();
      expect(find.text('app'), findsOneWidget);
    });

    testWidgets('API 37: refused for good -> app settings', (tester) async {
      native((_) => state(sdk: 37, granted: false));
      await pump(tester, lan);
      expect(calls, ['status']); // the system dialog would not show: not requested
      await tester.tap(find.byKey(const Key('lan.settings')));
      await tester.pump();
      expect(calls.last, 'openSettings');
    });

    testWidgets('API 37: revoked while in the background -> blocked again on resume', (tester) async {
      var granted = true;
      native((_) => state(sdk: 37, granted: granted));
      expect(await pump(tester, lan), 1);
      granted = false;
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();
      expect(find.text('Accès au réseau local'), findsOneWidget);
      granted = true; // re-granted in the settings
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();
      expect(find.text('app'), findsOneWidget);
    });

    testWidgets('loopback (adb reverse) and https: the channel is not even asked', (tester) async {
      native((_) => state(sdk: 37, granted: false));
      expect(await pump(tester, parse('http://127.0.0.1:8000/api/v1/')), 1);
      expect(calls, isEmpty);
    });

    testWidgets('no native side (desktop, tests): the app runs', (tester) async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(
        channel,
        (call) async => throw MissingPluginException(),
      );
      expect(await pump(tester, lan), 1); // MissingPluginException -> not required
      expect(find.text('app'), findsOneWidget);
    });
  });

  testWidgets('ConfigErrorApp explains a missing API_URL', (tester) async {
    try {
      AppConfig.parse(apiUrl: '');
    } on AppConfigException catch (error) {
      await tester.pumpWidget(ConfigErrorApp(error.message));
    }
    expect(find.textContaining('API_URL'), findsOneWidget);
  });
}
