# Jena User Flows

These are the canonical product flows after ADR-002. They center decisions, policy, verification, and memory. Ordinary file browsing remains in Windows Explorer.

## Flow 1 - I Need Space

1. The user opens Jena.
2. Home shows current free space, target free space, and the remaining gap. Example: `C: 6 GB free`, `Target: 20 GB`, `Need: 14 GB`.
3. Jena shows uniquely counted opportunities such as development dependencies, old Downloads, inactive projects, and verified cold-storage candidates.
4. The user selects **Build Recovery Plan**.
5. Jena creates a deterministic sequence with space gain, reason, risk, confidence, and recovery path for every action.
6. The user approves actions individually.
7. Jena revalidates policy and current state immediately before each operation, runs approved work asynchronously, verifies outcomes, and records receipts.

Nothing happens merely because Jena found an opportunity or built a plan.

## Flow 2 - Understand a Project

1. The user opens Projects.
2. Jena shows actual project roots from user-selected Project Libraries.
3. A project entry shows lifecycle state, total size, and a non-overlapping breakdown of Source, Dependencies, Caches, Assets, and Other.
4. Jena shows meaningful Git state and last meaningful activity when available.
5. Available actions include **Open in Explorer**, **Clean Regenerable Data**, **Mark Active**, **Mark Paused**, **Mark Inactive**, **Never Archive**, **Ignore**, and **Archive** when policy allows.
6. Explicit lifecycle and protection choices persist after restart and override heuristics.

Jena does not navigate the project's files internally as a replacement for Explorer.

## Flow 3 - Archive a Project

1. The user chooses **Archive** for an eligible project.
2. Jena analyzes current size, reproducible exclusions, expected archive size, expected recovery, Git state, destination, and policy.
3. Jena presents the plan and exclusions before approval.
4. After approval, Jena runs the operation through TaskManager.
5. Jena creates and closes the archive through CompressionService.
6. 7-Zip reopens and tests the archive.
7. Jena validates the member set, manifest, file sizes, and hashes.
8. Jena records the archive hash, location, metadata, and `VERIFIED` state.
9. Only after verification does Jena keep the source or move it to the Windows Recycle Bin according to the approved policy. Recycle Bin is the safe default.

Project source is never removed before the archive is verified.

## Flow 4 - Find an Old Project

1. Months later, the user searches for a project such as `Old Portfolio`.
2. Jena returns the durable project and archive record even when the source is no longer local.
3. Jena shows lifecycle state, archive name, location, provider and account when applicable, verification state, restore-test state, and recovery instructions.
4. The user can choose **Open Location** or **Restore**.
5. Restore extracts to staging, validates the result, refuses destination collisions, and only then places the project in its destination.

Remembering where recoverable project state lives is a key Jena value.

## Flow 5 - AI Helps Manage the Workstation

This is a future flow, not v0.4.0 implementation scope.

1. The user asks an AI for space while protecting named work.
2. The AI queries structured Jena facts through a bounded interface.
3. Jena returns current projects, policies, opportunities, recovery paths, and operation capabilities without secrets.
4. The AI proposes semantic actions.
5. Jena independently validates the proposal against current facts and policy.
6. The user approves specific actions.
7. Jena executes only approved operations and records their verified results.

The AI never receives unrestricted destructive access and cannot claim user approval.

## Flow 6 - Normal File Management

1. The user asks to inspect a file, project, archive, or storage location manually.
2. Jena uses the Windows Shell to open or reveal the item in Explorer.
3. Explorer handles navigation, thumbnails, previews, file opening, manual moves, and manual deletion.
4. Jena records only information or actions that contribute to its workstation memory, policies, or verified workflows.

Jena does not duplicate ordinary file management without a documented, high-value Jena-specific reason.
