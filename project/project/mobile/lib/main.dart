import 'package:flutter/material.dart';

import 'screens/home_screen.dart';

void main() {
  runApp(const FileSearchApp());
}

class FileSearchApp extends StatelessWidget {
  const FileSearchApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Intelligent File Search',
      theme: ThemeData(
        colorSchemeSeed: Colors.indigo,
        useMaterial3: true,
      ),
      home: const HomeScreen(),
      debugShowCheckedModeBanner: false,
    );
  }
}
