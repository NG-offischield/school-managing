import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'app_test.dart' show Harness;

/// Profile -> « Mon compte et paramètres » (school_core AccountScreen): the
/// fields offered are the ones the server declares editable for this role.
/// Widget test against the fake API, not E2E.
void main() {
  setUpAll(() => initializeDateFormatting('fr_FR'));

  testWidgets('staff: profile opens « Mon compte » with the fields of the role', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    await tester.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text('Profil')));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.byKey(const Key('profile.account')),
      200,
      scrollable: find.byType(Scrollable).last,
    );
    await tester.tap(find.byKey(const Key('profile.account')));
    await tester.pumpAndSettle();
    expect(find.text('Mon compte'), findsOneWidget);
    for (final field in ['phone', 'address']) {
      expect(find.byKey(Key('account.field.$field')), findsOneWidget, reason: field);
    }
    for (final field in ['occupation']) {
      expect(find.byKey(Key('account.field.$field')), findsNothing, reason: field);
    }
    expect(find.byKey(const Key('account.field.email')), findsNothing); // login: administration only
  });
}
