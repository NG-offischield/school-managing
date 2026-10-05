import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:school_core/school_core.dart';
import 'package:school_core/testing.dart';
import 'package:school_guardian/app.dart';
import 'package:school_guardian/data/guardian_repository.dart';
import 'package:school_guardian/presentation/camera/qr_camera.dart';

import 'fake_api.dart';

class Harness {
  Harness({bool live = false}) {
    api = ApiClient(baseUrl: 'http://testserver/api/v1/', client: MockClient(fake.call));
    auth = AuthService(api, store, requiredRole: 'GUARDIAN');
    repository = GuardianRepository(api);
    if (live) {
      realtime = () => RealtimeClient(
        api,
        socketUri('http://testserver/api/v1/'),
        channelFactory: (uri, headers) => channels[channels.length] = FakeChannel(),
        refresh: auth.refreshSession,
      );
    }
  }

  final fake = FakeApi();
  final store = MemoryTokenStore();
  final channels = <int, FakeChannel>{};
  late final ApiClient api;
  late final AuthService auth;
  late final GuardianRepository repository;
  RealtimeClient Function()? realtime;

  /// Gate camera; null = keyboard / reader only.
  QrCamera Function()? camera;

  Future<void> start(WidgetTester tester, {Size size = const Size(1080, 2400), double ratio = 2.6}) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = ratio;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(GuardianApp(auth: auth, repository: repository, realtime: realtime, camera: camera));
    await auth.restore();
    await tester.pumpAndSettle();
  }

  Future<void> login(WidgetTester tester, FakePerson who, {String? password}) async {
    await tester.enterText(find.byKey(const Key('login.identifier')), who.email);
    await tester.enterText(find.byKey(const Key('login.password')), password ?? who.password);
    await tester.pump();
    await tester.tap(find.byKey(const Key('login.submit')));
    await tester.pumpAndSettle();
  }

  Future<void> tab(WidgetTester tester, String label) async {
    await tester.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text(label)));
    await tester.pumpAndSettle();
  }
}
