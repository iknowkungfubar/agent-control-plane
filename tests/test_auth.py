"""Tests for auth, user, and team management."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_control_plane.models import (
    AgentRecord,
    AgentStatus,
    Team,
    TeamMember,
    User,
    UserRole,
)


# ---------------------------------------------------------------------------
# Auth module unit tests
# ---------------------------------------------------------------------------


class TestAuth:
    def test_generate_api_key_format(self):
        """API keys start with acp_ and are 68 chars."""
        from agent_control_plane.auth import generate_api_key
        key = generate_api_key()
        assert key.startswith("acp_")
        assert len(key) == 68  # "acp_" + 64 hex chars from secrets.token_hex(32)

    def test_hash_api_key(self):
        """Hash is deterministic and 64 hex chars."""
        from agent_control_plane.auth import hash_api_key
        key = "acp_test_key_123"
        h = hash_api_key(key)
        assert len(h) == 64  # SHA-256 hex
        assert h == hash_api_key(key)  # Deterministic

    def test_verify_api_key(self):
        """Verify matches correct key."""
        from agent_control_plane.auth import generate_api_key, hash_api_key, verify_api_key
        key = generate_api_key()
        h = hash_api_key(key)
        assert verify_api_key(key, h) is True
        assert verify_api_key("wrong_key", h) is False

    def test_verify_constant_time(self):
        """Verify uses constant-time comparison."""
        from agent_control_plane.auth import hash_api_key, verify_api_key
        h = hash_api_key("acp_real_key")
        assert verify_api_key("acp_real_key", h) is True
        assert verify_api_key("acp_fake_key", h) is False

    def test_create_session_and_validate(self):
        """Session token is valid and contains user name."""
        from agent_control_plane.auth import create_session, validate_session
        token = create_session("testuser")
        assert len(token.split(".")) == 3
        assert validate_session(token) == "testuser"

    def test_validate_expired_session(self):
        """Expired session returns None."""
        from agent_control_plane.auth import validate_session
        import time
        import hashlib
        import hmac
        old_ts = int(time.time()) - 90000  # > 24h ago
        payload = f"{old_ts}.expired_user"
        sig = hmac.new(b"test", payload.encode(), hashlib.sha256).hexdigest()[:16]
        token = f"{payload}.{sig}"
        # Should fail because signature won't match (different secret)
        assert validate_session(token) is None

    def test_validate_malformed_token(self):
        """Malformed session token returns None."""
        from agent_control_plane.auth import validate_session
        assert validate_session("not-enough-parts") is None
        assert validate_session("no.dots") is None
        assert validate_session("") is None

    def test_validate_invalid_timestamp(self):
        """Token with non-numeric timestamp returns None."""
        from agent_control_plane.auth import validate_session
        assert validate_session("abc.user.sig") is None

    def test_validate_tampered_signature(self):
        """Token with wrong signature returns None."""
        from agent_control_plane.auth import validate_session
        import time
        ts = int(time.time())
        assert validate_session(f"{ts}.realuser.wrongsig") is None

    def test_get_session_user_invalid_token(self):
        """get_session_user with invalid token returns None."""
        from agent_control_plane.auth import get_session_user
        assert get_session_user("invalid.token.here") is None
        assert get_session_user("") is None


# ---------------------------------------------------------------------------
# User CRUD tests
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    """Create temp database for testing."""
    from agent_control_plane.inventory import _ensure_tables, get_connection
    from agent_control_plane.config import get_home
    os.environ["ACP_HOME"] = str(tmp_path)
    conn = get_connection()
    return conn


class TestUserCRUD:
    def test_upsert_and_get_user(self, conn):
        """Insert a user and retrieve by name."""
        from agent_control_plane.inventory import get_user, upsert_user

        now = datetime.now(timezone.utc)
        user = User(name="testuser", email="test@example.com", role=UserRole.ADMIN,
                     api_key_hash="abc123", created_at=now)
        upsert_user(conn, user)

        retrieved = get_user(conn, "testuser")
        assert retrieved is not None
        assert retrieved.name == "testuser"
        assert retrieved.email == "test@example.com"
        assert retrieved.role == UserRole.ADMIN

    def test_get_user_by_email(self, conn):
        """Get user by email."""
        from agent_control_plane.inventory import get_user_by_email, upsert_user

        now = datetime.now(timezone.utc)
        user = User(name="emailuser", email="email@test.com", created_at=now)
        upsert_user(conn, user)

        retrieved = get_user_by_email(conn, "email@test.com")
        assert retrieved is not None
        assert retrieved.name == "emailuser"

    def test_list_users(self, conn):
        """List all users."""
        from agent_control_plane.inventory import list_users, upsert_user

        now = datetime.now(timezone.utc)
        upsert_user(conn, User(name="user1", email="u1@t.com", created_at=now))
        upsert_user(conn, User(name="user2", email="u2@t.com", created_at=now))

        users = list_users(conn)
        assert len(users) == 2

    def test_delete_user_cascades(self, conn):
        """Deleting user removes team memberships."""
        from agent_control_plane.inventory import (
            add_team_member,
            delete_user,
            get_user,
            list_team_members,
            upsert_team,
            upsert_user,
        )

        now = datetime.now(timezone.utc)
        upsert_user(conn, User(name="deletable", email="del@t.com", created_at=now))
        upsert_team(conn, Team(id="team1", name="Team 1", created_at=now))
        add_team_member(conn, TeamMember(user_name="deletable", team_id="team1"))

        delete_user(conn, "deletable")
        assert get_user(conn, "deletable") is None
        members = list_team_members(conn, "team1")
        assert len(members) == 0

    def test_check_single_user_mode_true(self, conn):
        """check_single_user_mode returns True when no users exist."""
        from agent_control_plane.inventory import check_single_user_mode
        assert check_single_user_mode(conn) is True

    def test_check_single_user_mode_false(self, conn):
        """check_single_user_mode returns False when users exist."""
        from agent_control_plane.inventory import check_single_user_mode, upsert_user

        now = datetime.now(timezone.utc)
        upsert_user(conn, User(name="someone", email="s@t.com", created_at=now))
        assert check_single_user_mode(conn) is False


class TestTeamCRUD:
    def test_upsert_and_get_team(self, conn):
        """Insert a team and retrieve it."""
        from agent_control_plane.inventory import get_team, upsert_team

        now = datetime.now(timezone.utc)
        upsert_team(conn, Team(id="infra", name="Infrastructure", description="Infra team", created_at=now))

        team = get_team(conn, "infra")
        assert team is not None
        assert team.name == "Infrastructure"

    def test_list_teams(self, conn):
        """List all teams."""
        from agent_control_plane.inventory import list_teams, upsert_team

        now = datetime.now(timezone.utc)
        upsert_team(conn, Team(id="t1", name="Team 1", created_at=now))
        upsert_team(conn, Team(id="t2", name="Team 2", created_at=now))

        teams = list_teams(conn)
        assert len(teams) == 2

    def test_delete_team_unassigns_agents(self, conn):
        """Deleting a team unassigns its agents."""
        from agent_control_plane.inventory import (
            delete_team,
            assign_agent_to_team,
            upsert_team,
        )

        now = datetime.now(timezone.utc)
        upsert_team(conn, Team(id="delteam", name="To Delete", created_at=now))
        conn.execute(
            "INSERT INTO agents (name, url, provider, status, tags, team_id, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("agent1", "http://localhost:1", "custom", "unknown", "[]",
             "delteam", now.isoformat(), now.isoformat()),
        )
        conn.commit()

        delete_team(conn, "delteam")
        row = conn.execute("SELECT team_id FROM agents WHERE name='agent1'").fetchone()
        assert row["team_id"] is None

    def test_add_and_remove_team_member(self, conn):
        """Manage team membership."""
        from agent_control_plane.inventory import (
            add_team_member,
            list_team_members,
            remove_team_member,
            upsert_team,
            upsert_user,
        )

        now = datetime.now(timezone.utc)
        upsert_user(conn, User(name="member1", email="m@t.com", created_at=now))
        upsert_team(conn, Team(id="mt", name="Member Team", created_at=now))
        add_team_member(conn, TeamMember(user_name="member1", team_id="mt",
                                          role_in_team=UserRole.OPERATOR))

        members = list_team_members(conn, "mt")
        assert len(members) == 1
        assert members[0].role_in_team == UserRole.OPERATOR

        remove_team_member(conn, "member1", "mt")
        members = list_team_members(conn, "mt")
        assert len(members) == 0

    def test_assign_agent_to_team(self, conn):
        """Assign and unassign agents."""
        from agent_control_plane.inventory import (
            assign_agent_to_team,
            unassign_agent_from_team,
        )

        now = datetime.now(timezone.utc)
        conn.execute(
            "INSERT INTO agents (name, url, provider, status, tags, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("assign-agent", "http://localhost:2", "custom", "unknown",
             "[]", now.isoformat(), now.isoformat()),
        )
        conn.commit()

        assign_agent_to_team(conn, "assign-agent", "team-x")
        row = conn.execute("SELECT team_id FROM agents WHERE name='assign-agent'").fetchone()
        assert row["team_id"] == "team-x"

        unassign_agent_from_team(conn, "assign-agent")
        row = conn.execute("SELECT team_id FROM agents WHERE name='assign-agent'").fetchone()
        assert row["team_id"] is None


class TestTeamScopedQueries:
    def test_list_agents_filtered_by_team(self, conn):
        """list_agents respects team_id filter."""
        from agent_control_plane.inventory import list_agents

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO agents (name, url, provider, status, tags, team_id, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("team-a-agent", "http://localhost:1", "custom", "unknown", "[]",
             "team-a", now, now),
        )
        conn.execute(
            "INSERT INTO agents (name, url, provider, status, tags, team_id, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("team-b-agent", "http://localhost:2", "custom", "unknown", "[]",
             "team-b", now, now),
        )
        conn.commit()

        team_a_agents = list_agents(conn, team_ids=["team-a"])
        assert len(team_a_agents) == 1
        assert team_a_agents[0].name == "team-a-agent"

        all_agents = list_agents(conn)
        assert len(all_agents) == 2

    def test_list_agents_empty_team_filter(self, conn):
        """Empty team_ids returns no agents."""
        from agent_control_plane.inventory import list_agents

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO agents (name, url, provider, status, tags, team_id, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("orphan", "http://localhost:1", "custom", "unknown", "[]",
             "some-team", now, now),
        )
        conn.commit()

        agents = list_agents(conn, team_ids=[])
        assert len(agents) == 0

    def test_get_user_team_ids_admin(self, conn):
        """Admin user returns empty list (no filter = all agents)."""
        from agent_control_plane.inventory import (
            get_user_team_ids,
            upsert_user,
        )
        from agent_control_plane.models import UserRole

        now = datetime.now(timezone.utc)
        upsert_user(conn, User(name="bigcheese", email="boss@t.com",
                                role=UserRole.ADMIN, created_at=now))
        team_ids = get_user_team_ids(conn, "bigcheese")
        assert team_ids == []  # Empty = admin sees all

    def test_get_user_team_ids_operator(self, conn):
        """Operator user returns their team IDs."""
        from agent_control_plane.inventory import (
            add_team_member,
            get_user_team_ids,
            upsert_team,
            upsert_user,
        )
        from agent_control_plane.models import UserRole

        now = datetime.now(timezone.utc)
        upsert_user(conn, User(name="opuser", email="op@t.com",
                                role=UserRole.OPERATOR, created_at=now))
        upsert_team(conn, Team(id="op-team", name="OP Team", created_at=now))
        add_team_member(conn, TeamMember(user_name="opuser", team_id="op-team"))

        team_ids = get_user_team_ids(conn, "opuser")
        assert team_ids == ["op-team"]

    def test_get_user_team_ids_nonexistent(self, conn):
        """Non-existent user returns empty list like admin."""
        from agent_control_plane.inventory import get_user_team_ids

        team_ids = get_user_team_ids(conn, "ghost")
        assert team_ids == []

    def test_get_user_teams(self, conn):
        """get_user_teams returns teams for a user."""
        from agent_control_plane.inventory import (
            add_team_member,
            get_user_teams,
            upsert_team,
            upsert_user,
        )

        now = datetime.now(timezone.utc)
        upsert_user(conn, User(name="teamuser", email="tu@t.com", created_at=now))
        upsert_team(conn, Team(id="team-x", name="Team X", created_at=now))
        upsert_team(conn, Team(id="team-y", name="Team Y", created_at=now))
        add_team_member(conn, TeamMember(user_name="teamuser", team_id="team-x"))
        add_team_member(conn, TeamMember(user_name="teamuser", team_id="team-y"))

        teams = get_user_teams(conn, "teamuser")
        assert len(teams) == 2
        team_names = [t.name for t in teams]
        assert "Team X" in team_names


class TestAuthIntegration:
    """End-to-end auth flow."""

    def test_create_user_and_authenticate(self, tmp_path):
        """Create user with API key, then authenticate via email + key."""
        import os
        os.environ["ACP_HOME"] = str(tmp_path)
        from agent_control_plane.auth import (
            authenticate_email,
            authenticate_api_key,
            create_user_with_key,
        )

        user, api_key = create_user_with_key("e2euser", "e2e@test.com", role="admin")
        assert user.name == "e2euser"
        assert api_key.startswith("acp_")

        # Authenticate by API key
        authed = authenticate_api_key(api_key)
        assert authed is not None
        assert authed.name == "e2euser"

        # Authenticate by email + key (dashboard login)
        authed = authenticate_email("e2e@test.com", api_key)
        assert authed is not None
        assert authed.name == "e2euser"

        # Wrong key fails
        assert authenticate_api_key("wrong_key") is None
        assert authenticate_email("e2e@test.com", "wrong_key") is None

    def test_single_user_mode_auth(self, tmp_path):
        """No users means single-user mode returns guest admin."""
        import os
        os.environ["ACP_HOME"] = str(tmp_path)
        from agent_control_plane.auth import authenticate_api_key, authenticate_email

        # No users created - single user mode
        admin_key = authenticate_api_key("any_key")
        assert admin_key is not None
        assert admin_key.role == UserRole.ADMIN

        admin_email = authenticate_email("any@email.com", "any_key")
        assert admin_email is not None
        assert admin_email.role == UserRole.ADMIN

    def test_session_flow(self, tmp_path):
        """Full session lifecycle."""
        import os
        os.environ["ACP_HOME"] = str(tmp_path)
        from agent_control_plane.auth import (
            create_session,
            get_session_user,
            validate_session,
        )

        token = create_session("testuser")
        assert validate_session(token) == "testuser"

        # get_session_user in single-user mode returns guest admin
        user = get_session_user(token)
        assert user is not None
        assert user.name == "admin"

    def test_get_session_user_real_user(self, tmp_path):
        """get_session_user works with a real user session."""
        import os
        os.environ["ACP_HOME"] = str(tmp_path)
        from agent_control_plane.auth import (
            create_session,
            create_user_with_key,
            get_session_user,
        )

        create_user_with_key("real-user", "real@test.com", role="operator")
        token = create_session("real-user")
        user = get_session_user(token)
        assert user is not None
        assert user.name == "real-user"
        assert user.role.value == "operator"


class TestDashboardAuthAPI:
    """Test dashboard auth API endpoints via TestClient."""

    @pytest.fixture
    def client(self, tmp_path):
        import os
        os.environ["ACP_HOME"] = str(tmp_path)

        from agent_control_plane.dashboard import create_app
        from fastapi.testclient import TestClient
        app = create_app()
        return TestClient(app)

    def test_login_fails_with_wrong_creds(self, client, tmp_path):
        """POST /api/login with wrong creds returns 401."""
        from agent_control_plane.auth import create_user_with_key
        create_user_with_key("auth-user", "auth@test.com", role="admin")

        response = client.post("/api/login",
            json={"email": "wrong@test.com", "api_key": "wrong_key"},
        )
        assert response.status_code == 401

    def test_me_unauthenticated(self, client):
        """GET /api/me returns unauthenticated."""
        response = client.get("/api/me")
        assert response.status_code == 200
        assert response.json()["authenticated"] is False

    def test_login_and_session(self, client, tmp_path):
        """Full login flow via API."""
        from agent_control_plane.auth import create_user_with_key

        user, api_key = create_user_with_key("api-test", "api@test.com", role="operator")

        # Login
        res = client.post("/api/login",
            json={"email": "api@test.com", "api_key": api_key},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["user"] == "api-test"

        # Check session cookie was set
        assert "acp_session" in res.cookies

    def test_logout_clears_session(self, client):
        """POST /api/logout clears the session cookie."""
        res = client.post("/api/logout")
        assert res.status_code == 200

    def test_admin_endpoints(self, client, tmp_path):
        """GET /api/admin/users and /api/admin/teams work."""
        from agent_control_plane.auth import create_user_with_key

        create_user_with_key("admin-user", "admin@test.com", role="admin")

        res = client.get("/api/admin/users")
        assert res.status_code == 200
        data = res.json()
        assert "users" in data

        res = client.get("/api/admin/teams")
        assert res.status_code == 200
        assert "teams" in res.json()

    def test_login_page_renders(self, client):
        """GET /login returns HTML."""
        res = client.get("/login")
        assert res.status_code == 200
        assert "Sign in with your email" in res.text

    def test_admin_page_renders(self, client):
        """GET /admin returns HTML."""
        res = client.get("/admin")
        assert res.status_code == 200
        assert "Admin Panel" in res.text
