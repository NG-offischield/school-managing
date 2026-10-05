/// Android 10 -> 17 configuration of the four apps, checked from the files
/// themselves (run from packages/school_core): SDK levels in ONE shared
/// script, permissions declared once and justified, clear text in debug only.
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

const apps = ['teacher', 'parent', 'guardian', 'staff'];

String read(String path) => File(path).readAsStringSync();

String app(String name, String path) => read('../../apps/$name/android/app/$path');

int intSetting(String source, String name) =>
    int.parse(RegExp('ext\\.$name\\s*=\\s*(\\d+)').firstMatch(source)!.group(1)!);

void main() {
  final shared = read('../../gradle/school-android.gradle');

  test('shared levels: minSdk 29 (Android 10), compileSdk and targetSdk 37 (Android 17)', () {
    expect(intSetting(shared, 'schoolMinSdk'), 29);
    expect(intSetting(shared, 'schoolCompileSdk'), 37);
    expect(intSetting(shared, 'schoolTargetSdk'), 37);
    expect(shared, contains('minSdk = schoolMinSdk'));
    expect(shared, contains('targetSdk = schoolTargetSdk'));
    expect(shared, contains('compileSdk = schoolCompileSdk'));
  });

  for (final name in apps) {
    test('$name applies the shared script and sets no level of its own', () {
      final gradle = app(name, 'build.gradle.kts');
      expect(gradle, contains('apply(from = "../../../../gradle/school-android.gradle")'));
      expect(gradle, isNot(matches(RegExp(r'^\s*(minSdk|targetSdk|compileSdk)\s*=', multiLine: true))));
    });

    test('$name: release manifest has no clear text and no extra permission', () {
      final manifest = app(name, 'src/main/AndroidManifest.xml');
      expect(manifest, isNot(contains('usesCleartextTraffic')));
      expect(manifest, isNot(contains('networkSecurityConfig')));
      // Permissions come from school_core only (INTERNET, ACCESS_LOCAL_NETWORK).
      expect(manifest, isNot(contains('<uses-permission')));
    });

    test('$name: clear text only in the DEBUG source set', () {
      expect(app(name, 'src/debug/AndroidManifest.xml'), contains('@xml/network_security_config_debug'));
      expect(
        File('../../apps/$name/android/app/src/main/res/xml/network_security_config_debug.xml').existsSync(),
        isFalse,
      );
    });

    test('$name: no backend address written in the sources', () {
      final sources = Directory('../../apps/$name/lib')
          .listSync(recursive: true)
          .whereType<File>()
          .where((f) => f.path.endsWith('.dart'))
          .map((f) => f.readAsStringSync())
          .join('\n');
      expect(sources, isNot(matches(RegExp(r'https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}'))));
      expect(sources, contains('AppConfig.fromEnvironment()'));
      expect(sources, contains('LocalNetworkGate('));
    });
  }

  test('camera: the guardian app only (mobile_scanner, minSdk-compatible), never the others', () {
    for (final name in apps) {
      final pubspec = read('../../apps/$name/pubspec.yaml');
      expect(pubspec.contains('mobile_scanner:'), name == 'guardian', reason: name);
    }
    expect(read('../../apps/guardian/pubspec.yaml'), contains('mobile_scanner: ^7.4.2'));
  });

  test('school_core Android module: same levels, both network permissions, nothing else', () {
    final gradle = read('android/build.gradle.kts');
    expect(gradle, contains('compileSdk = 37'));
    expect(gradle, contains('minSdk = 29'));
    final manifest = read('android/src/main/AndroidManifest.xml');
    final permissions = RegExp(
      r'<uses-permission android:name="([^"]+)"',
    ).allMatches(manifest).map((m) => m.group(1)).toList();
    expect(permissions, ['android.permission.INTERNET', 'android.permission.ACCESS_LOCAL_NETWORK']);
  });

  test('opening a PDF: private FileProvider, cache/shared/ only, no storage permission', () {
    final manifest = read('android/src/main/AndroidManifest.xml');
    expect(manifest, contains('android:name="cm.schoolmanaging.school_core.SchoolCoreFileProvider"'));
    expect(manifest, contains('android:exported="false"'));
    expect(manifest, isNot(contains('STORAGE')));
    expect(manifest, isNot(contains('requestLegacyExternalStorage')));
    final paths = read('android/src/main/res/xml/school_core_file_paths.xml');
    final shared = RegExp(
      r'<([a-z-]+-path)[^>]*path="([^"]*)"',
    ).allMatches(paths).map((m) => '${m[1]}:${m[2]}').toList();
    expect(shared, ['cache-path:shared/']); // never root-path, files-path or external storage
  });

  test('the Android 17 permission is only requested behind an SDK_INT check', () {
    final plugin = read('android/src/main/kotlin/cm/schoolmanaging/school_core/SchoolCorePlugin.kt');
    expect(plugin, contains('fun required(sdkInt: Int): Boolean = sdkInt >= SINCE_SDK'));
    expect(plugin, contains('const val SINCE_SDK = 37'));
    final request = plugin.indexOf('private fun request(');
    expect(
      plugin.indexOf('LocalNetworkPolicy.required(sdk)', request),
      lessThan(plugin.indexOf('requestPermissions(', request)),
    );
    // No compile-time reference to the API 37 constant: the string is safe on API 29.
    expect(plugin, isNot(contains('Manifest.permission.ACCESS_LOCAL_NETWORK')));
  });
}
