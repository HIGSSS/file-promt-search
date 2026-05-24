import 'package:flutter/material.dart';

import 'screens/home_screen.dart';
import 'services/upload_background_service.dart';

void main() async {
  // WidgetsFlutterBinding нужен до любых platform-channel вызовов.
  WidgetsFlutterBinding.ensureInitialized();
  // Регистрируем Foreground Service один раз при старте приложения.
  await initUploadService();
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
