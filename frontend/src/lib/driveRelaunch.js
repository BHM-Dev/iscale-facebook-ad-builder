export function resolveDriveRelaunch(groups, handoff) {
    const requestedIds = [...new Set((handoff?.drive_file_ids || []).map(String))];
    const nameById = new Map(requestedIds.map((id, index) => [
        id,
        handoff?.drive_file_names?.[index] || id,
    ]));
    const selectedGroupIds = new Set();
    const missingFiles = [];
    requestedIds.forEach(fileId => {
        const group = (groups || []).find(item => item.assets?.some(asset => String(asset.drive_file_id) === fileId));
        if (group) selectedGroupIds.add(group.id);
        else missingFiles.push(nameById.get(fileId));
    });
    return { requestedIds, selectedGroupIds, missingFiles };
}
