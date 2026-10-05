import 'package:flutter_test/flutter_test.dart';
import 'package:school_core/school_core.dart';

void main() {
  group('looksLikeQrToken: only a student card goes to the server', () {
    test('the existing token format (secrets.token_urlsafe(32))', () {
      expect(looksLikeQrToken('wE4IDi9RqtPcY1_iGW_sTwhmn8zj4fIvgGKWKSK5Njw'), isTrue);
      expect(looksLikeQrToken('  wE4IDi9RqtPcY1_iGW_sTwhmn8zj4fIvgGKWKSK5Njw\n'), isTrue); // reader newline
    });

    test('anything else a camera may read is refused locally', () {
      for (final value in [
        '',
        'abc',
        'https://exemple.com/promo?id=42',
        'WIFI:S:Ecole;T:WPA;P:secret;;',
        'BEGIN:VCARD',
        'token with spaces inside 1234567890',
        'é' * 40,
        'a' * 257,
      ]) {
        expect(looksLikeQrToken(value), isFalse, reason: value);
      }
    });
  });

  group('ScanGuard: no double submission', () {
    test('one submission at a time', () {
      final guard = ScanGuard();
      expect(guard.tryBegin('card-A'), isTrue);
      expect(guard.busy, isTrue);
      expect(guard.tryBegin('card-B'), isFalse); // concurrent: refused
      guard.end('card-A', answered: true);
      expect(guard.tryBegin('card-B'), isTrue);
    });

    test('the same card answered a moment ago is not sent again', () {
      var now = DateTime(2026, 10, 5, 7, 30);
      final guard = ScanGuard(window: const Duration(seconds: 5), clock: () => now);
      expect(guard.tryBegin('card-A'), isTrue);
      guard.end('card-A', answered: true);
      now = now.add(const Duration(seconds: 2));
      expect(guard.isRepeat('card-A'), isTrue);
      expect(guard.tryBegin('card-A'), isFalse);
      expect(guard.tryBegin('card-B'), isTrue); // another pupil right after: fine
      guard.end('card-B', answered: true);
      now = now.add(const Duration(seconds: 6));
      expect(guard.tryBegin('card-A'), isTrue); // later on: a real new scan
    });

    test('a submission that never reached the server can be retried at once', () {
      final guard = ScanGuard();
      expect(guard.tryBegin('card-A'), isTrue);
      guard.end('card-A', answered: false); // network down
      expect(guard.isRepeat('card-A'), isFalse);
      expect(guard.tryBegin('card-A'), isTrue);
    });
  });
}
