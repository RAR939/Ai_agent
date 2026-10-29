from abc import ABC, abstractmethod
from pathlib import Path

from src.schemas import (
    AgentResult,
    Deadline,
    DeadlineCard,
    DeadlineEvent,
    IndexStatus,
    Lesson,
    Message,
    MessageContext,
    PendingItem,
    Report,
    ScheduleImport,
    SearchHit,
    ToolCall,
)


class Provider(ABC):
    @abstractmethod
    def ask(
        self,
        question: str,
        history: list[dict],
    ) -> AgentResult:
        pass

    @abstractmethod
    def list_deadlines(
        self,
        discipline=None,
        status=None,
    ) -> list[Deadline]:
        pass

    @abstractmethod
    def get_deadline_history(
        self,
        id: int,
    ) -> list[DeadlineEvent]:
        pass

    @abstractmethod
    def list_pending(self) -> list[PendingItem]:
        pass

    @abstractmethod
    def resolve_pending(
        self,
        id: int,
        accept: bool,
    ) -> None:
        pass

    @abstractmethod
    def lessons_between(
        self,
        date_from: str,
        date_to: str,
        discipline=None,
    ) -> list[Lesson]:
        pass

    @abstractmethod
    def load_schedule(
        self,
        path: str,
        dry_run=False,
    ) -> ScheduleImport:
        pass

    @abstractmethod
    def get_message_context(
        self,
        msg_id: str,
        before=3,
        after=3,
    ) -> MessageContext:
        pass

    @abstractmethod
    def get_card(
        self,
        deadline_id: int,
    ) -> DeadlineCard:
        pass

    @abstractmethod
    def file_abs_path(self, f) -> str:
        pass

    @abstractmethod
    def index_status(self) -> list[IndexStatus]:
        pass

    @abstractmethod
    def reindex(self, chat: str) -> dict:
        pass

    @abstractmethod
    def process_new(self, chat: str) -> Report:
        pass

    @abstractmethod
    def corpus_stats(self) -> dict:
        pass


class MockProvider(Provider):
    def __init__(self):
        self.deadlines = [
            Deadline(
                id=1,
                discipline="electro",
                kind="lab",
                task="Лабораторная №2",
                due_at="2026-10-30T23:59:00+03:00",
                due_text="до конца недели",
                fuzzy=False,
                status="active",
                source_msg="electro:1042",
                confidence=0.96,
                updated_at="2026-10-29T12:00:00+03:00",
                attachments=[],
            ),
            Deadline(
                id=2,
                discipline="probability",
                kind="hw",
                task="Домашняя работа",
                due_at="2026-11-02T23:59:00+03:00",
                due_text="до понедельника",
                fuzzy=False,
                status="active",
                source_msg="probability:318",
                confidence=0.91,
                updated_at="2026-10-29T12:05:00+03:00",
                attachments=[],
            ),
            Deadline(
                id=3,
                discipline="electro",
                kind="midterm",
                task="Контрольная работа",
                due_at="2026-11-05T23:59:00+03:00",
                due_text="5 ноября",
                fuzzy=False,
                status="active",
                source_msg="electro:1070",
                confidence=0.94,
                updated_at="2026-10-29T12:10:00+03:00",
                attachments=[],
            ),
            Deadline(
                id=4,
                discipline="electro",
                kind="lab",
                task="Лабораторная №3",
                due_at="2026-11-08T23:59:00+03:00",
                due_text="8 ноября",
                fuzzy=False,
                status="active",
                source_msg="electro:1085",
                confidence=0.93,
                updated_at="2026-10-29T12:15:00+03:00",
                attachments=[],
            ),
            Deadline(
                id=5,
                discipline="data_models",
                kind="lab",
                task="Лабораторная работа №2",
                due_at="2026-11-10T23:59:00+03:00",
                due_text="10 ноября",
                fuzzy=False,
                status="active",
                source_msg="data_models:204",
                confidence=0.90,
                updated_at="2026-10-29T12:20:00+03:00",
                attachments=[],
            ),
            Deadline(
                id=6,
                discipline="probability",
                kind="other",
                task="Подготовка к контрольной",
                due_at="2026-11-12T23:59:00+03:00",
                due_text="12 ноября",
                fuzzy=False,
                status="active",
                source_msg="probability:350",
                confidence=0.88,
                updated_at="2026-10-29T12:25:00+03:00",
                attachments=[],
            ),
        ]

        self.history = {
            1: [
                DeadlineEvent(
                    id=1,
                    deadline_id=1,
                    old_due=None,
                    new_due="2026-10-20T23:59:00+03:00",
                    source_msg="electro:1001",
                    changed_at="2026-10-10T14:00:00+03:00",
                ),
                DeadlineEvent(
                    id=2,
                    deadline_id=1,
                    old_due="2026-10-20T23:59:00+03:00",
                    new_due="2026-10-28T23:59:00+03:00",
                    source_msg="electro:1024",
                    changed_at="2026-10-18T15:30:00+03:00",
                ),
                DeadlineEvent(
                    id=3,
                    deadline_id=1,
                    old_due="2026-10-28T23:59:00+03:00",
                    new_due="2026-11-05T23:59:00+03:00",
                    source_msg="electro:1042",
                    changed_at="2026-10-27T11:45:00+03:00",
                ),
            ]
        }

        self.pending = [
            PendingItem(
                id=1,
                candidate=Deadline(
                    discipline="electro",
                    kind="lab",
                    task="Лабораторная работа №4",
                    due_at="2026-11-05T23:59:00+03:00",
                    due_text="до 5 ноября",
                    fuzzy=False,
                    status="pending",
                    source_msg="electro:1100",
                    confidence=0.62,
                    attachments=[],
                ),
                matched_id=1,
                reason="ambiguous_match",
                source_text=(
                    "Лабораторную работу №4 нужно "
                    "подготовить до 5 ноября."
                ),
                created_at="2026-10-29T11:00:00+03:00",
            ),
            PendingItem(
                id=2,
                candidate=Deadline(
                    discipline="probability",
                    kind="hw",
                    task="Домашнее задание",
                    due_at=None,
                    due_text="до пятницы",
                    fuzzy=True,
                    status="pending",
                    source_msg="probability:370",
                    confidence=0.55,
                    attachments=[],
                ),
                matched_id=None,
                reason="low_confidence",
                source_text=(
                    "Домашнее задание постарайтесь "
                    "сдать до пятницы."
                ),
                created_at="2026-10-29T11:10:00+03:00",
            ),
        ]

        self.lessons = [
            Lesson(
                id=1,
                discipline="electro",
                lesson_type="lecture",
                start="2026-11-02T09:00:00+03:00",
                end="2026-11-02T10:30:00+03:00",
                teacher="Преподаватель",
                room="305",
            ),
            Lesson(
                id=2,
                discipline="probability",
                lesson_type="lab",
                start="2026-11-02T12:00:00+03:00",
                end="2026-11-02T13:30:00+03:00",
                teacher="Преподаватель",
                room="412",
            ),
            Lesson(
                id=3,
                discipline="data_models",
                lesson_type="seminar",
                start="2026-11-03T10:30:00+03:00",
                end="2026-11-03T12:00:00+03:00",
                teacher="Преподаватель",
                room="208",
            ),
            Lesson(
                id=4,
                discipline="programming",
                lesson_type="lab",
                start="2026-11-03T14:00:00+03:00",
                end="2026-11-03T15:30:00+03:00",
                teacher="Преподаватель",
                room="501",
            ),
            Lesson(
                id=5,
                discipline="math",
                lesson_type="lecture",
                start="2026-11-04T09:00:00+03:00",
                end="2026-11-04T10:30:00+03:00",
                teacher="Преподаватель",
                room="302",
            ),
            Lesson(
                id=6,
                discipline="electro",
                lesson_type="lab",
                start="2026-11-04T12:00:00+03:00",
                end="2026-11-04T13:30:00+03:00",
                teacher="Преподаватель",
                room="407",
            ),
        ]

    def ask(
        self,
        question: str,
        history: list[dict],
    ) -> AgentResult:
        source = SearchHit(
            chunk_id="electro:1040-1051",
            chat="electro",
            text=(
                "Лабораторную работу №2 необходимо "
                "сдать до конца недели."
            ),
            ts_from="2026-10-29T10:00:00+03:00",
            ts_to="2026-10-29T10:10:00+03:00",
            roles=["starosta"],
            msg_ids=["electro:1042"],
            discipline="electro",
            score=0.94,
        )

        trace = [
            ToolCall(
                tool="search",
                args={"query": question},
                result_preview="Найдено 5 сообщений",
                duration=0.18,
                error=None,
            ),
            ToolCall(
                tool="list_deadlines",
                args={"status": "active"},
                result_preview="Найдено 6 дедлайнов",
                duration=0.07,
                error=None,
            ),
        ]

        return AgentResult(
            text=(
                "На этой неделе найдено несколько дедлайнов. "
                "Ближайший — Лабораторная №2."
            ),
            sources=[source],
            trace=trace,
            pending_ids=[],
        )

    def list_deadlines(
        self,
        discipline=None,
        status=None,
    ) -> list[Deadline]:
        result = self.deadlines

        if discipline is not None:
            result = [
                item
                for item in result
                if item.discipline == discipline
            ]

        if status is not None:
            result = [
                item
                for item in result
                if item.status == status
            ]

        return result

    def get_deadline_history(
        self,
        id: int,
    ) -> list[DeadlineEvent]:
        return self.history.get(id, [])

    def list_pending(self) -> list[PendingItem]:
        return self.pending

    def resolve_pending(
        self,
        id: int,
        accept: bool,
    ) -> None:
        item = next(
            (
                pending
                for pending in self.pending
                if pending.id == id
            ),
            None,
        )

        if item is None:
            return

        if accept:
            new_deadline = item.candidate.model_copy()

            new_deadline.id = (
                max(
                    deadline.id or 0
                    for deadline in self.deadlines
                )
                + 1
            )

            new_deadline.status = "active"

            self.deadlines.append(new_deadline)

        self.pending = [
            pending
            for pending in self.pending
            if pending.id != id
        ]

    def lessons_between(
        self,
        date_from: str,
        date_to: str,
        discipline=None,
    ) -> list[Lesson]:
        result = self.lessons

        if discipline is not None:
            result = [
                lesson
                for lesson in result
                if lesson.discipline == discipline
            ]

        return result

    def load_schedule(
        self,
        path: str,
        dry_run=False,
    ) -> ScheduleImport:
        return ScheduleImport(
            ok=True,
            lessons=self.lessons[:3],
            errors=[],
            replaced=0 if dry_run else 3,
        )

    def get_message_context(
        self,
        msg_id: str,
        before=3,
        after=3,
    ) -> MessageContext:
        target = Message(
            id=msg_id,
            chat="electro",
            ts="2026-10-29T10:05:00+03:00",
            author="STAROSTA",
            role="starosta",
            text=(
                "Лабораторную работу №2 необходимо "
                "сдать до конца недели."
            ),
            reply_to=None,
            forwarded=False,
            src="messages.html#message1042",
            attachments=[],
        )

        message_before = Message(
            id="electro:1041",
            chat="electro",
            ts="2026-10-29T10:02:00+03:00",
            author="STUDENT_1",
            role="student",
            text="Когда нужно принести отчёт?",
            reply_to=None,
            forwarded=False,
            src="messages.html#message1041",
            attachments=[],
        )

        message_after = Message(
            id="electro:1043",
            chat="electro",
            ts="2026-10-29T10:07:00+03:00",
            author="STAROSTA",
            role="starosta",
            text="Требования к работе отправлены выше.",
            reply_to=None,
            forwarded=False,
            src="messages.html#message1043",
            attachments=[],
        )

        return MessageContext(
            target=target,
            before=[message_before],
            after=[message_after],
        )

    def get_card(
        self,
        deadline_id: int,
    ) -> DeadlineCard:
        deadline = next(
            (
                item
                for item in self.deadlines
                if item.id == deadline_id
            ),
            self.deadlines[0],
        )

        discussion = [
            SearchHit(
                chunk_id="electro:1040-1051",
                chat="electro",
                text=(
                    "Обсуждали срок сдачи "
                    "лабораторной работы №2."
                ),
                ts_from="2026-10-29T10:00:00+03:00",
                ts_to="2026-10-29T10:10:00+03:00",
                roles=["student", "starosta"],
                msg_ids=["electro:1041", "electro:1042"],
                discipline="electro",
                score=0.91,
            )
        ]

        return DeadlineCard(
            deadline=deadline,
            history=self.get_deadline_history(deadline_id),
            discussion=discussion,
        )

    def file_abs_path(self, f) -> str:
        return str(
            Path("data")
            / "raw"
            / f.path
        )

    def index_status(self) -> list[IndexStatus]:
        return [
            IndexStatus(
                chat="electro",
                messages=1842,
                period_from="2026-09-01T00:00:00+03:00",
                period_to="2026-10-29T12:45:00+03:00",
                last_processed="2026-10-29T12:45:00+03:00",
                chunks=220,
                deadlines=7,
            ),
            IndexStatus(
                chat="probability",
                messages=1506,
                period_from="2026-09-02T00:00:00+03:00",
                period_to="2026-10-29T12:42:00+03:00",
                last_processed="2026-10-29T12:42:00+03:00",
                chunks=180,
                deadlines=6,
            ),
            IndexStatus(
                chat="data_models",
                messages=938,
                period_from="2026-09-05T00:00:00+03:00",
                period_to="2026-10-28T18:10:00+03:00",
                last_processed="2026-10-28T18:10:00+03:00",
                chunks=112,
                deadlines=5,
            ),
        ]

    def reindex(self, chat: str) -> dict:
        return {
            "chat": chat,
            "status": "ok",
            "chunks": 220,
        }

    def process_new(self, chat: str) -> Report:
        return Report(
            processed=24,
            added=2,
            moved=1,
            cancelled=0,
            pending=1,
            skipped_prefilter=4,
            failed=0,
        )

    def corpus_stats(self) -> dict:
        return {
            "messages": 4286,
            "deadlines": 18,
            "chunks": 512,
            "chats": 3,
        }


class RealProvider(Provider):
    def ask(self, question: str, history: list[dict]) -> AgentResult:
        raise NotImplementedError(
            "RealProvider будет подключён после готовности агента."
        )

    def list_deadlines(self, discipline=None, status=None):
        raise NotImplementedError

    def get_deadline_history(self, id: int):
        raise NotImplementedError

    def list_pending(self):
        raise NotImplementedError

    def resolve_pending(self, id: int, accept: bool):
        raise NotImplementedError

    def lessons_between(
        self,
        date_from: str,
        date_to: str,
        discipline=None,
    ):
        raise NotImplementedError

    def load_schedule(self, path: str, dry_run=False):
        raise NotImplementedError

    def get_message_context(
        self,
        msg_id: str,
        before=3,
        after=3,
    ):
        raise NotImplementedError

    def get_card(self, deadline_id: int):
        raise NotImplementedError

    def file_abs_path(self, f):
        raise NotImplementedError

    def index_status(self):
        raise NotImplementedError

    def reindex(self, chat: str):
        raise NotImplementedError

    def process_new(self, chat: str):
        raise NotImplementedError

    def corpus_stats(self):
        raise NotImplementedError