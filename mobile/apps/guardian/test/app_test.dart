import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:school_core/school_core.dart';

import 'fake_api.dart';
import 'harness.dart';

void main() {
  setUpAll(() => initializeDateFormatting('fr_FR'));

  testWidgets('home: MY passages of the day only, closures to come, notifications', (tester) async {
    final h = Harness();
    await h.start(tester);
    expect(find.text('School Managing'), findsOneWidget);
    await h.login(tester, h.fake.a);
    expect(find.text('Bonjour Moussa'), findsOneWidget);
    expect(find.text('1 arrivée(s) enregistrée(s) aujourd\'hui'), findsOneWidget); // B's scan not counted
    expect(find.text('2 passage(s) au total, par vous'), findsOneWidget);
    expect(find.text('Vacances de Noël'), findsOneWidget);
    expect(find.text('Fête passée'), findsNothing);
    expect(find.text('Portail fermé à 18 h'), findsOneWidget);

    await h.tab(tester, 'Passages');
    expect(find.text('Léa Mbarga'), findsOneWidget);
    expect(find.text('QR non reconnu'), findsOneWidget);
    expect(find.text('Tom Ndiaye'), findsNothing); // another guardian's scan: never
    for (final r in h.fake.requests) {
      expect(r.url.toString(), isNot(contains('gb')));
    }
  });

  testWidgets('scan at the gate: the server decides result, arrival and solvency', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    await h.tab(tester, 'Portail');
    await tester.enterText(find.byKey(const Key('scan.token')), qrLea);
    await tester.testTextInput.receiveAction(TextInputAction.done); // a QR reader ends with Enter
    await tester.pumpAndSettle();
    expect(find.text('Arrivée enregistrée'), findsOneWidget);
    expect(find.text('Léa Mbarga'), findsOneWidget);
    expect(find.text('6e A'), findsOneWidget);
    expect(find.text('En retard (35 min)'), findsOneWidget);
    expect(find.text('Échéance dépassée'), findsOneWidget); // status only, never an amount
    expect(find.textContaining('XAF'), findsNothing);

    await tester.enterText(find.byKey(const Key('scan.token')), qrOtherSchool);
    await tester.pump();
    await tester.tap(find.byKey(const Key('scan.submit')));
    await tester.pumpAndSettle();
    expect(find.text('QR inconnu'), findsOneWidget);
    expect(find.text('Léa Mbarga'), findsNothing);

    await h.tab(tester, 'Passages');
    expect(find.textContaining('4 passage(s)'), findsOneWidget);
  });

  testWidgets('wrong password, suspended account, account of another role', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a, password: 'mauvais-mot');
    expect(find.textContaining('Identifiant ou mot de passe incorrect'), findsOneWidget);
    h.fake.suspended.add('ga');
    await h.login(tester, h.fake.a);
    expect(find.textContaining('compte suspendu'), findsOneWidget);
    await h.login(tester, h.fake.parent);
    expect(find.textContaining('n\'est pas un compte gardien'), findsOneWidget);
    expect(h.auth.status, AuthStatus.signedOut);
  });

  testWidgets('activation of the account created by the school', (tester) async {
    final h = Harness();
    await h.start(tester);
    await tester.tap(find.byKey(const Key('login.activate')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('activation.code')), h.fake.activationCode);
    await tester.pump();
    await tester.tap(find.byKey(const Key('activation.check')));
    await tester.pumpAndSettle();
    const password = 'Nouveau-Portail-2026!';
    await tester.enterText(find.byKey(const Key('activation.password')), password);
    await tester.enterText(find.byKey(const Key('activation.confirmation')), password);
    await tester.pump();
    await tester.tap(find.byKey(const Key('activation.complete')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('activation.toLogin')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('login.password')), password);
    await tester.pump();
    await tester.tap(find.byKey(const Key('login.submit')));
    await tester.pumpAndSettle();
    expect(find.text('Bonjour Moussa'), findsOneWidget);
  });

  testWidgets('communication: notifications only (spec §8: no messaging, no complaints for guardians)', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    await h.tab(tester, 'Alertes');
    expect(find.text('Portail fermé à 18 h'), findsOneWidget);
    expect(find.widgetWithText(Tab, 'Messages'), findsNothing);
    expect(find.widgetWithText(Tab, 'Réclamations'), findsNothing);
    await tester.tap(find.text('Portail fermé à 18 h'));
    await tester.pumpAndSettle();
    expect(find.text('Travaux.'), findsOneWidget);
    expect(h.fake.requests.where((r) => r.url.path.endsWith('notifications/n1/read/')), hasLength(1));
    expect(
      h.fake.requests.where((r) => r.url.path.contains('conversations') || r.url.path.contains('complaints')),
      isEmpty,
    );
  });

  testWidgets('live: pushed notification; refused socket (4401) expires the session', (tester) async {
    final h = Harness(live: true);
    await h.start(tester);
    await h.login(tester, h.fake.a);
    final socket = h.channels[0]!;
    socket.push({'type': 'auth.ok', 'membership': 'm-ga', 'unread_notifications': 1});
    await tester.pumpAndSettle();
    socket.push({
      'type': 'notification',
      'data': {
        'id': 'n9',
        'notification_type': 'ANNOUNCEMENT',
        'title': 'Exercice incendie',
        'message': '10 h',
        'is_read': false,
        'created_at': '2026-10-05T10:00:00+01:00',
      },
    });
    await tester.pumpAndSettle();
    expect(find.text('2'), findsWidgets);
    h.fake.revokeAll();
    socket.closeWith(4401);
    await tester.pumpAndSettle();
    expect(h.auth.status, AuthStatus.signedOut);
    expect(find.textContaining('session a expiré'), findsOneWidget);
  });

  testWidgets('expired token -> login; offline explained; logout revokes', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    h.fake.revokeAll();
    await h.tab(tester, 'Passages');
    await tester.tap(find.byKey(const Key('scans.previous')));
    await tester.pumpAndSettle();
    expect(h.auth.status, AuthStatus.signedOut);
    expect(find.textContaining('session a expiré'), findsOneWidget);

    await h.login(tester, h.fake.a);
    h.fake.offline = true;
    await tester.tap(find.byTooltip('Actualiser'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Connexion au serveur impossible'), findsOneWidget);
    h.fake.offline = false;
    await tester.tap(find.text('Réessayer'));
    await tester.pumpAndSettle();
    await h.tab(tester, 'Profil');
    await tester.tap(find.byKey(const Key('profile.logout')));
    await tester.pumpAndSettle();
    expect(find.text('Vous êtes déconnecté.'), findsOneWidget);
    expect(h.store.refreshToken, isNull);
    expect(h.fake.tokens.values.where((p) => p.key == 'ga'), isEmpty);
  });

  testWidgets('small phone (360 dp): every tab renders without overflow', (tester) async {
    final h = Harness();
    await h.start(tester, size: const Size(720, 1280), ratio: 2.0);
    await h.login(tester, h.fake.a);
    for (final label in ['Portail', 'Passages', 'Alertes', 'Profil', 'Accueil']) {
      await h.tab(tester, label);
      expect(tester.takeException(), isNull, reason: label);
    }
  });
}
