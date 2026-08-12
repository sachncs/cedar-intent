"""Policy class hierarchy.

Three concrete policy shapes share a common :class:`Kind` base,
each with its own lifecycle and materialization path.

Attributes:
    Kind: Abstract base for every policy in cedrus.
    Draft: In-memory policy under authoring; carries the principal,
        action and resource scopes the caller supplied plus an
        optional typed intent produced by a generator.
    Existing: Policy imported from raw Cedar source rather than
        drafted by a generator.
    Compiled: Final-form policy produced by
        :meth:`~cedrus.space.Space.apply` after the compiler has
        rendered the intent and Cedar has accepted the source.

See Also:
    :mod:`cedrus.policies.base`: Abstract :class:`Kind` base class.
    :mod:`cedrus.policies.draft`: :class:`Draft` subclass.
    :mod:`cedrus.policies.existing`: :class:`Existing` subclass.
    :mod:`cedrus.policies.compiled`: :class:`Compiled` subclass.
"""

from cedrus.policies.base import Kind
from cedrus.policies.compiled import Compiled
from cedrus.policies.draft import Draft
from cedrus.policies.existing import Existing

__all__ = ["Compiled", "Draft", "Existing", "Kind"]