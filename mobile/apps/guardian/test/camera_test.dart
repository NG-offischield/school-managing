/// Camera scanner of the gate, with a fake camera (no hardware): the whole
/// path Accueil -> Scanner -> camera -> QR -> existing endpoint -> result ->
/// history, and every failure the guardian can meet.
library;

import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:school_guardian/presentation/camera/camera_scan_screen.dart';
import 'package:school_guardian/presentation/camera/qr_camera.dart';

import 'fake_api.dart';
import 'harness.dart';

class FakeQrCamera implements QrCamera {
  final _codes = StreamController<String>.broadcast();
  QrCameraFailure? failOnStart;

  /// Holds start() open, like the system permission dialog.
  Completer<void>? dialog;
  int starts = 0;
  int stops = 0;
  int torch = 0;
  bool disposed = false;

  void show(String value) => _codes.add(value);

  @override
  Stream<String> get codes => _codes.stream;

  @override
  Future<void> start() async {
    starts++;
    await dialog?.future;
    final failure = failOnStart;
    if (failure != null) throw QrCameraException(failure);
  }

  @override
  Future<void> stop() async => stops++;

  @override
  Future<void> toggleTorch() async => torch++;

  @override
  Future<void> dispose() async => disposed = true;

  @override
  Widget preview(BuildContext context) => const ColoredBox(key: Key('fake.preview'), color: Colors.black);
}

void main() {
  setUpAll(() => initializeDateFormatting('fr_FR'));

  late FakeQrCamera camera;
  late Harness h;

  Future<void> signIn(WidgetTester tester, {Size size = const Size(1080, 2400), double ratio = 2.6}) async {
    camera = FakeQrCamera();
    h = Harness()..camera = () => camera;
    await h.start(tester, size: size, ratio: ratio);
    await h.login(tester, h.fake.a);
  }

  /// Portail tab, then the main button: the camera screen.
  Future<void> openCamera(WidgetTester tester) async {
    await h.tab(tester, 'Portail');
    await tester.tap(find.byKey(const Key('scan.camera')));
    await tester.pumpAndSettle();
  }

  int serverScans() => h.fake.requests.where((r) => r.url.path.endsWith('qr/scans/')).length;

  testWidgets('Accueil -> Scanner: camera, QR, server result, history updated', (tester) async {
    await signIn(tester);
    expect(find.text('1 arrivée(s) enregistrée(s) aujourd\'hui'), findsOneWidget);
    await tester.tap(find.byKey(const Key('home.scan')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('fake.preview')), findsOneWidget); // camera open straight away
    expect(find.byKey(const Key('camera.hint')), findsOneWidget);
    expect(camera.starts, 1);

    camera.show(qrLea);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('fake.preview')), findsNothing); // closed after the read
    expect(camera.stops, greaterThanOrEqualTo(1));
    expect(camera.disposed, isTrue);
    expect(serverScans(), 1);
    final sent = h.fake.requests.lastWhere((r) => r.url.path.endsWith('qr/scans/'));
    expect(sent.body, '{"token":"$qrLea"}'); // the existing protocol: the token, nothing else
    expect(find.text('Arrivée enregistrée'), findsOneWidget);
    expect(find.text('Échéance dépassée'), findsOneWidget); // status, never an amount
    expect(find.textContaining('XAF'), findsNothing);
    expect(find.text('Scanner la carte suivante'), findsOneWidget);

    await h.tab(tester, 'Accueil'); // refreshed by the scan, no manual reload
    expect(find.text('2 arrivée(s) enregistrée(s) aujourd\'hui'), findsOneWidget);
    await h.tab(tester, 'Passages');
    expect(find.text('Léa Mbarga'), findsWidgets);
  });

  testWidgets('double scan: one read per opening, the same card is not sent twice', (tester) async {
    await signIn(tester);
    await openCamera(tester);
    camera.show(qrLea);
    camera.show(qrLea); // the same frame decoded twice
    await tester.pumpAndSettle();
    expect(serverScans(), 1);

    await tester.tap(find.byKey(const Key('scan.camera')));
    await tester.pumpAndSettle();
    camera.show(qrLea); // the card is still in front of the camera
    await tester.pumpAndSettle();
    expect(serverScans(), 1);
    expect(find.textContaining('Cette carte vient d\'être lue'), findsOneWidget);
    expect(find.text('Arrivée enregistrée'), findsOneWidget); // the previous answer stays
  });

  testWidgets('a QR that is not a student card is ignored and never sent', (tester) async {
    await signIn(tester);
    await openCamera(tester);
    camera.show('https://exemple.com/promo?id=42');
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const Key('camera.invalid')), findsOneWidget);
    camera.show('WIFI:S:Ecole;T:WPA;P:secret;;');
    await tester.pump(const Duration(seconds: 4));
    expect(find.byKey(const Key('fake.preview')), findsOneWidget); // still scanning
    expect(serverScans(), 0);

    camera.show(qrLea);
    await tester.pumpAndSettle();
    expect(serverScans(), 1);
    expect(find.text('Arrivée enregistrée'), findsOneWidget);
  });

  testWidgets('revoked card and card of another school: the server refuses', (tester) async {
    await signIn(tester);
    await openCamera(tester);
    camera.show(qrRevoked);
    await tester.pumpAndSettle();
    expect(find.text('QR révoqué'), findsOneWidget);

    await tester.tap(find.byKey(const Key('scan.camera')));
    await tester.pumpAndSettle();
    camera.show(qrOtherSchool);
    await tester.pumpAndSettle();
    expect(find.text('QR inconnu'), findsOneWidget); // another school's token is unknown here
    expect(find.text('Léa Mbarga'), findsNothing);
  });

  testWidgets('camera refused: explanation, settings, manual entry; then allowed', (tester) async {
    final calls = <String>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(const MethodChannel('school_core/local_network'), (
      call,
    ) async {
      calls.add(call.method);
      return true;
    });
    await signIn(tester);
    camera.failOnStart = QrCameraFailure.permissionDenied;
    await openCamera(tester);
    expect(find.text('Accès à l\'appareil photo refusé'), findsOneWidget);
    expect(find.textContaining('Aucune photo n\'est enregistrée ni envoyée'), findsOneWidget);

    await tester.tap(find.byKey(const Key('camera.settings')));
    await tester.pump();
    expect(calls, ['openSettings']);

    camera.failOnStart = null; // granted in the system dialog
    await tester.tap(find.byKey(const Key('camera.retry')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('camera.hint')), findsOneWidget);

    await tester.tap(find.byType(BackButton)); // back always leaves the scanner
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('scan.camera')), findsOneWidget);
    expect(serverScans(), 0);
  });

  testWidgets('permission revoked while in the background: stopped, then explained on return', (tester) async {
    await signIn(tester);
    await openCamera(tester);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump();
    expect(camera.stops, 1); // camera released in the background
    camera.failOnStart = QrCameraFailure.permissionDenied; // revoked in the settings
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(camera.starts, 2);
    expect(find.text('Accès à l\'appareil photo refusé'), findsOneWidget);

    await tester.tap(find.byKey(const Key('camera.manual')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('scan.manual')), findsOneWidget); // reader / keyboard still there
  });

  testWidgets('the system permission dialog is not asked again in a loop (Android 10)', (tester) async {
    await signIn(tester);
    camera.dialog = Completer<void>();
    camera.failOnStart = QrCameraFailure.permissionDenied;
    await h.tab(tester, 'Portail');
    await tester.tap(find.byKey(const Key('scan.camera')));
    await tester.pump();
    // The dialog makes the app inactive, then resumed when answered (« Refuser »).
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    camera.dialog!.complete();
    await tester.pumpAndSettle();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(camera.starts, 1); // asked once; again only from the button
    expect(camera.stops, 0);
    expect(find.text('Accès à l\x27appareil photo refusé'), findsOneWidget);
  });

  testWidgets('back from the background: the camera restarts and still reads', (tester) async {
    await signIn(tester);
    await openCamera(tester);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(camera.starts, 2);
    camera.show(qrLea);
    await tester.pumpAndSettle();
    expect(find.text('Arrivée enregistrée'), findsOneWidget);
  });

  testWidgets('no camera on the device: manual entry offered', (tester) async {
    await signIn(tester);
    camera.failOnStart = QrCameraFailure.unavailable;
    await openCamera(tester);
    expect(find.text('Appareil photo indisponible'), findsOneWidget);
    expect(find.byKey(const Key('camera.retry')), findsNothing);
    await tester.tap(find.byKey(const Key('camera.manual')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('scan.camera')), findsOneWidget);
  });

  testWidgets('cancel: nothing sent', (tester) async {
    await signIn(tester);
    await openCamera(tester);
    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('scan.camera')), findsOneWidget);
    expect(serverScans(), 0);
    expect(camera.disposed, isTrue);
  });

  testWidgets('nothing read in 45 s: camera stopped, retry', (tester) async {
    await signIn(tester);
    await openCamera(tester);
    await tester.pump(const Duration(seconds: 46));
    expect(find.text('Aucune carte détectée'), findsOneWidget);
    expect(camera.stops, 1);
    await tester.tap(find.byKey(const Key('camera.retry')));
    await tester.pumpAndSettle();
    camera.show(qrLea);
    await tester.pumpAndSettle();
    expect(find.text('Arrivée enregistrée'), findsOneWidget);
  });

  testWidgets('low light: the torch can be switched on', (tester) async {
    await signIn(tester);
    await openCamera(tester);
    await tester.tap(find.byKey(const Key('camera.torch')));
    await tester.pump();
    expect(camera.torch, 1);
  });

  testWidgets('network down: not recorded, said so, retry once back', (tester) async {
    await signIn(tester);
    await openCamera(tester);
    h.fake.offline = true;
    camera.show(qrLea);
    await tester.pumpAndSettle();
    expect(find.textContaining('le passage n\'est PAS enregistré'), findsOneWidget);
    expect(find.text('Arrivée enregistrée'), findsNothing);
    expect(h.fake.scanCalls, 0);

    h.fake.offline = false;
    await tester.tap(find.byKey(const Key('scan.retry'))); // same card, not a repeat: never answered
    await tester.pumpAndSettle();
    expect(h.fake.scanCalls, 1);
    expect(find.text('Arrivée enregistrée'), findsOneWidget);
  });

  testWidgets('small phone, landscape: the scanner and its panels fit', (tester) async {
    await signIn(tester, size: const Size(1280, 720), ratio: 2); // 640 x 360 dp
    await openCamera(tester);
    expect(tester.takeException(), isNull);
    expect(find.byKey(const Key('camera.hint')), findsOneWidget);
    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();
    camera.failOnStart = QrCameraFailure.permissionDenied;
    await tester.tap(find.byKey(const Key('scan.camera')));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.byKey(const Key('camera.panel')), findsOneWidget);
  });

  testWidgets('the scanner screen alone returns the first valid token', (tester) async {
    final fake = FakeQrCamera();
    String? read;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => TextButton(
            onPressed: () async => read = await CameraScanScreen.open(context, () => fake),
            child: const Text('go'),
          ),
        ),
      ),
    );
    await tester.tap(find.text('go'));
    await tester.pumpAndSettle();
    fake.show('  $qrLea  ');
    await tester.pumpAndSettle();
    expect(read, qrLea);
  });

  test('the real camera keeps text only: QR format, no image', () {
    final source = File('lib/presentation/camera/qr_camera.dart').readAsStringSync();
    expect(source, contains('formats: const [BarcodeFormat.qrCode]'));
    expect(source, contains('returnImage: false'));
    expect(source, isNot(contains('capture.image')));
  });
}
