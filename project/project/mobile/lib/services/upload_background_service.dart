import 'dart:async';
import 'dart:io';
import 'dart:ui';

import 'package:flutter_background_service/flutter_background_service.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

import 'api_service.dart';

const _kChannelId = 'ifs_upload_channel';
const _kNotifId = 1001;
const _kEventStart = 'startUpload';
const _kEventReady = 'serviceReady';
const _kEventStop = 'stopService';
const _kEventProgress = 'progress';
const _kEventDone = 'done';

Future<void> initUploadService() async {
  const channel = AndroidNotificationChannel(
    _kChannelId,
    'Загрузка файлов',
    description: 'Прогресс фоновой загрузки файлов на сервер',
    importance: Importance.low,
  );
  await FlutterLocalNotificationsPlugin()
      .resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin>()
      ?.createNotificationChannel(channel);

  await FlutterBackgroundService().configure(
    androidConfiguration: AndroidConfiguration(
      onStart: _onStart,
      autoStart: false,
      isForegroundMode: true,
      notificationChannelId: _kChannelId,
      initialNotificationTitle: 'Загрузка файлов',
      initialNotificationContent: 'Инициализация...',
      foregroundServiceNotificationId: _kNotifId,
      foregroundServiceTypes: [AndroidForegroundType.dataSync],
    ),
    iosConfiguration: IosConfiguration(autoStart: false),
  );
}

/// Запускает Foreground Service с ready-хэндшейком:
/// ждём сигнал от сервиса что он готов, затем отправляем данные.
/// Это убирает гонку между запуском сервиса и отправкой события.
Future<void> startUpload(List<String> filePaths, {required int totalBytes}) async {
  final service = FlutterBackgroundService();

  // Если сервис завис от предыдущей сессии — останавливаем его.
  if (await service.isRunning()) {
    service.invoke(_kEventStop, {});
    await Future.delayed(const Duration(milliseconds: 600));
  }

  // Подписываемся на ready-событие ДО старта сервиса, чтобы не пропустить.
  final readyCompleter = Completer<void>();
  StreamSubscription? readySub;
  readySub = service.on(_kEventReady).listen((_) {
    readySub?.cancel();
    if (!readyCompleter.isCompleted) readyCompleter.complete();
  });

  await service.startService();

  // Ждём сигнал готовности с таймаутом 4 секунды.
  try {
    await readyCompleter.future.timeout(const Duration(seconds: 4));
  } on TimeoutException {
    readySub?.cancel();
    // Продолжаем в любом случае — на некоторых устройствах сигнал может
    // приходить позже, но событие startUpload всё равно будет принято.
  }

  service.invoke(_kEventStart, {
    'paths': filePaths,
    'totalBytes': totalBytes,
  });
}

Stream<Map<String, dynamic>?> get uploadProgressStream =>
    FlutterBackgroundService().on(_kEventProgress);

Stream<Map<String, dynamic>?> get uploadDoneStream =>
    FlutterBackgroundService().on(_kEventDone);

// ---------------------------------------------------------------------------
// Точка входа фонового изолята
// ---------------------------------------------------------------------------

@pragma('vm:entry-point')
void _onStart(ServiceInstance service) async {
  DartPluginRegistrant.ensureInitialized();

  // Сигнализируем UI-изоляту что мы готовы принимать события.
  service.invoke(_kEventReady, {});

  // Обработка запроса на остановку от UI (например, если сервис завис).
  service.on(_kEventStop).listen((_) => service.stopSelf());

  service.on(_kEventStart).listen((data) async {
    if (data == null) return;

    final paths = List<String>.from(data['paths'] as List);
    final files = paths.map(File.new).toList();
    final precomputedTotal = (data['totalBytes'] as num?)?.toInt() ?? 0;

    try {
      await ApiService.uploadPathsAndIndexBatched(
        files,
        precomputedTotalBytes: precomputedTotal,
        onProgress: (sent, total, path) {
          service.invoke(_kEventProgress, {
            'sentBytes': sent,
            'totalBytes': total,
            'currentFile': path,
          });

          if (service is AndroidServiceInstance) {
            final pct = total > 0 ? sent * 100 ~/ total : 0;
            service.setForegroundNotificationInfo(
              title: 'Загрузка файлов: $pct%',
              content: File(path).uri.pathSegments.last,
            );
          }
        },
      );

      service.invoke(_kEventDone, {'success': true});
      if (service is AndroidServiceInstance) {
        service.setForegroundNotificationInfo(
          title: 'Загрузка завершена',
          content: 'Файлы переданы — идёт индексация на сервере...',
        );
      }
    } catch (e) {
      service.invoke(_kEventDone, {'success': false, 'error': e.toString()});
      if (service is AndroidServiceInstance) {
        service.setForegroundNotificationInfo(
          title: 'Ошибка загрузки',
          content: e.toString(),
        );
      }
    } finally {
      await Future.delayed(const Duration(seconds: 3));
      service.stopSelf();
    }
  });
}
