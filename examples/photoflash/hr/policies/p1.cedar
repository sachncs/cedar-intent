// Pre-existing Cedar policy imported from disk to demonstrate
// how cedar-intent accepts existing policies and integrates them
// into verification and deployment workflows.

permit (
    principal is PhotoFlash::User,
    action == PhotoFlash::Action::"viewPhoto",
    resource is PhotoFlash::Photo
) when {
    principal.role == "admin" && !resource.private
};
