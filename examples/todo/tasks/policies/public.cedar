// Baseline policy: any authenticated user may view any task.

permit (
    principal is TodoApp::User,
    action == TodoApp::Action::"viewTask",
    resource is TodoApp::Task
);
