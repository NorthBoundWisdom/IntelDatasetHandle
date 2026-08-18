#include <QGuiApplication>
#include <QIcon>
#include <QQmlApplicationEngine>
#include <QUrl>

int main(int argc, char *argv[]) {
    QGuiApplication application(argc, argv);
    application.setApplicationName(QStringLiteral("Demo"));
    application.setOrganizationName(QStringLiteral("WeldDataWorkbench"));

    const QString iconPath = qEnvironmentVariable("WELD_DEMO_ICON");
    if (!iconPath.isEmpty()) {
        application.setWindowIcon(QIcon(iconPath));
    }

    const QString qmlFile = qEnvironmentVariable("WELD_QML_FILE");
    if (qmlFile.isEmpty()) {
        return 2;
    }

    QQmlApplicationEngine engine;
    const QString qmlImportPath = qEnvironmentVariable("WELD_QML_IMPORT_PATH");
    if (!qmlImportPath.isEmpty()) {
        engine.addImportPath(qmlImportPath);
    }
    engine.load(QUrl::fromLocalFile(qmlFile));
    if (engine.rootObjects().isEmpty()) {
        return 2;
    }
    return application.exec();
}
