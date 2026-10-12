import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'app_test.dart' show Harness;

/// « Plan de l'établissement » in the parent app (school_core PlansScreen):
/// from the home shortcuts and from the profile; the server decides who sees
/// the plan. Widget tests, not E2E.
void main() {
  setUpAll(() => initializeDateFormatting('fr_FR'));

  testWidgets('home shortcut -> plan of the school -> zoomable image', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    await tester.scrollUntilVisible(find.byKey(const Key('home.plans')), 300);
    await tester.tap(find.byKey(const Key('home.plans')));
    await tester.pumpAndSettle();
    expect(find.text('Plan général'), findsOneWidget);
    await tester.tap(find.text('Plan général'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('plan.image')), findsOneWidget);
    expect(find.byType(InteractiveViewer), findsOneWidget);
    expect(h.paths, contains('http://testserver/api/v1/plans/p1/file/'));
  });

  testWidgets('a parent outside the audience sees no plan (profile entry)', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.b);
    await tester.tap(find.byKey(const Key('home.profile')));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.byKey(const Key('profile.plans')), 200);
    await tester.tap(find.byKey(const Key('profile.plans')));
    await tester.pumpAndSettle();
    expect(find.text('Plan général'), findsNothing);
    expect(find.text("Aucun plan de l'établissement n'est disponible pour le moment."), findsOneWidget);
  });
}
