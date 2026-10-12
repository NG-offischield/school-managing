import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'app_test.dart' show Harness;

/// « Plan de l'établissement » in the teacher app (school_core PlansScreen)
/// against the fake API: the server decides who sees the plan. Widget tests,
/// not E2E.
void main() {
  setUpAll(() => initializeDateFormatting('fr_FR'));

  Future<void> openPlans(WidgetTester tester) async {
    await tester.tap(find.text('Profil'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('profile.plans')));
    await tester.pumpAndSettle();
  }

  testWidgets('profile -> plan of the school -> zoomable image', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    await openPlans(tester);
    expect(find.text('Plan général'), findsOneWidget);
    expect(find.text('Bâtiment A · RDC'), findsOneWidget);
    await tester.tap(find.text('Plan général'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('plan.image')), findsOneWidget);
    expect(find.byType(InteractiveViewer), findsOneWidget);
    final asked = h.fake.requests.map((r) => r.url.path).toList();
    expect(asked, containsAllInOrder(['/api/v1/plans/', '/api/v1/plans/p1/', '/api/v1/plans/p1/file/']));
  });

  testWidgets('a teacher outside the audience sees no plan', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.b);
    await openPlans(tester);
    expect(find.text('Plan général'), findsNothing);
    expect(find.text("Aucun plan de l'établissement n'est disponible pour le moment."), findsOneWidget);
  });
}
