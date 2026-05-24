import 'package:flutter_test/flutter_test.dart';

import 'package:intelligent_file_search/main.dart';

void main() {
  testWidgets('App starts smoke test', (WidgetTester tester) async {
    await tester.pumpWidget(const FileSearchApp());

    expect(find.byType(FileSearchApp), findsOneWidget);
  });
}
