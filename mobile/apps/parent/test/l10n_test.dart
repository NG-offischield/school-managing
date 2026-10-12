import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:provider/provider.dart';
import 'package:school_core/l10n_testing.dart';
import 'package:school_core/school_core.dart';
import 'package:school_parent/l10n/parent_en.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'app_test.dart' show Harness;

/// The parent app in English: every French key has an English text; a walk
/// through the screens shows no French text left except business data (names,
/// school, classes, subjects, typed messages: never translated); « Langue » in
/// « Mon compte » switches the OPEN app and the choice is kept on the phone.
/// Widget tests against the fake API, not E2E.

/// Data of the fake server (never translated): names, school, classes,
/// subjects, and texts the SERVER writes (notification titles, functions,
/// school breaks) — those stay in the server's language.
const businessData = {
  'École Test',
  'Awa Mbarga',
  'Awa',
  'Mbarga',
  'Léa',
  'Tom',
  'Zoé',
  'Ndiaye',
  'Paul',
  'Mathématiques',
  'Français',
  '6e A',
  '3e B',
  '4e C',
  'Réunion de rentrée',
  'Vie de l\'école',
  'Direction',
  'Trimestre 1',
  'Bâtiment A',
  'Plan général',
  'Mère',
  'École Les Palmiers',
  'Retards répétés',
};

void main() {
  setUpAll(() => initializeDateFormatting());
  tearDown(() => L10n.use(AppLanguage.fr));

  test('every French key of the parent app has an English text', () {
    final keys = frenchKeys('lib');
    final missing = keys.where((k) => !parentEnglish.containsKey(k) && !coreEnglish.containsKey(k)).toList();
    expect(missing, isEmpty, reason: '$missing');
  });

  testWidgets('a walk through the app in English shows no French text', (tester) async {
    L10n.use(AppLanguage.en);
    final h = Harness();
    await h.start(tester);
    final seen = <String, List<String>>{'sign-in': visibleTexts()};
    expect(find.text('Sign in'), findsWidgets);
    await h.login(tester, h.fake.a);
    final count = find.byType(NavigationDestination).evaluate().length;
    for (var i = 0; i < count; i++) {
      await tester.tap(find.byType(NavigationDestination).at(i));
      await tester.pumpAndSettle();
      seen['tab $i'] = visibleTexts();
    }
    await tester.tap(find.byType(NavigationDestination).first);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('home.profile')));
    await tester.pumpAndSettle();
    seen['profile'] = visibleTexts();
    await tester.scrollUntilVisible(
      find.byKey(const Key('profile.account')),
      200,
      scrollable: find.byType(Scrollable).last,
    );
    await tester.tap(find.byKey(const Key('profile.account')));
    await tester.pumpAndSettle();
    seen['account'] = visibleTexts();
    final french = {
      for (final e in seen.entries)
        if (frenchLooking(e.value, allowed: businessData).isNotEmpty)
          e.key: frenchLooking(e.value, allowed: businessData),
    };
    expect(french, isEmpty);
    // …and the interface really is in English, not merely « not French ».
    expect(seen['tab 0'], containsAll(['Home', 'Attendance', 'Timetable', 'Messages']));
    expect(seen['account'], containsAll(['My account', 'My contact details', 'Change my password']));
    expect(L10n.missing, isEmpty);
  });

  testWidgets('« Langue » switches the open app to English and back; kept on the phone, apart from the theme', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({ThemeController.key: 'dark'});
    final language = await LanguageController.load();
    final theme = await ThemeController.load();
    final h = Harness();
    await h.start(
      tester,
      wrap: (app) => MultiProvider(
        providers: [
          ChangeNotifierProvider<ThemeController>.value(value: theme),
          ChangeNotifierProvider<LanguageController>.value(value: language),
        ],
        child: app,
      ),
    );
    await h.login(tester, h.fake.a);
    await tester.tap(find.byType(NavigationDestination).first);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('home.profile')));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.byKey(const Key('profile.account')),
      200,
      scrollable: find.byType(Scrollable).last,
    );
    await tester.tap(find.byKey(const Key('profile.account')));
    await tester.pumpAndSettle();
    expect(find.text('Mon compte'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.byKey(const Key('account.password')),
      200,
      scrollable: find.byType(Scrollable).first,
    ); // below « Langue »: then fully visible
    await tester.tap(find.byKey(const Key('account.language.en')));
    await tester.pumpAndSettle();
    expect(find.text('My account'), findsOneWidget); // the open screen, at once
    expect(find.text('Language'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('Profile'), findsWidgets); // the screen below too
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString(LanguageController.key), 'en');
    expect(prefs.getString(ThemeController.key), 'dark'); // untouched by the language
    expect(Tokens.isDark, isTrue);
    await language.set(AppLanguage.fr);
    await tester.pumpAndSettle();
    expect(L10n.language, AppLanguage.fr);
    Tokens.use(Brightness.light);
  });
}
