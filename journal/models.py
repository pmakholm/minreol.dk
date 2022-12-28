from django.db import models
from polymorphic.models import PolymorphicModel
from users.models import User
from catalog.common.models import Item, ItemCategory
from .mixins import UserOwnedObjectMixin
from catalog.collection.models import Collection as CatalogCollection
from decimal import *
from enum import Enum
from markdownx.models import MarkdownxField
from django.utils import timezone
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils.translation import gettext_lazy as _
from django.core.validators import RegexValidator
from functools import cached_property
from django.db.models import Count, Avg
import django.dispatch
import math
import uuid
from catalog.common.utils import DEFAULT_ITEM_COVER, item_cover_path
from django.utils.baseconv import base62
from django.db.models import Q
from catalog.models import *
import mistune
from django.contrib.contenttypes.models import ContentType
from markdown import markdown


class VisibilityType(models.IntegerChoices):
    Public = 0, _('公开')
    Follower_Only = 1, _('仅关注者')
    Private = 2, _('仅自己')


def q_visible_to(viewer, owner):
    if viewer == owner:
        return Q()
    # elif viewer.is_blocked_by(owner):
    #     return Q(pk__in=[])
    elif viewer.is_following(owner):
        return Q(visibility__ne=2)
    else:
        return Q(visibility=0)


def query_visible(user):
    return Q(visibility=0) | Q(owner_id__in=user.following, visibility=1) | Q(owner_id=user.id)


def query_following(user):
    return Q(owner_id__in=user.following, visibility__lt=2) | Q(owner_id=user.id)


def query_item_category(item_category):
    classes = all_categories()[item_category]
    # q = Q(item__instance_of=classes[0])
    # for cls in classes[1:]:
    #     q = q | Q(instance_of=cls)
    # return q
    ct = all_content_types()
    contenttype_ids = [ct[cls] for cls in classes]
    return Q(item__polymorphic_ctype__in=sorted(contenttype_ids))


class Piece(PolymorphicModel, UserOwnedObjectMixin):
    url_path = 'piece'  # subclass must specify this
    uid = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)
    owner = models.ForeignKey(User, on_delete=models.PROTECT)
    visibility = models.PositiveSmallIntegerField(default=0)  # 0: Public / 1: Follower only / 2: Self only
    created_time = models.DateTimeField(default=timezone.now)  # auto_now_add=True  FIXME revert this after migration
    edited_time = models.DateTimeField(default=timezone.now)  # auto_now=True   FIXME revert this after migration
    metadata = models.JSONField(default=dict)
    attached_to = models.ForeignKey(User, null=True, default=None, on_delete=models.SET_NULL, related_name="attached_with")

    @property
    def uuid(self):
        return base62.encode(self.uid.int)

    @property
    def url(self):
        return f'/{self.url_path}/{self.uuid}' if self.url_path else None

    @property
    def absolute_url(self):
        return (settings.APP_WEBSITE + self.url) if self.url_path else None

    @property
    def api_url(self):
        return ('/api/' + self.url) if self.url_path else None


class Content(Piece):
    item = models.ForeignKey(Item, on_delete=models.PROTECT)

    @cached_property
    def mark(self):
        m = Mark(self.owner, self.item)
        m.review = self
        return m

    def __str__(self):
        return f"{self.uuid}@{self.item}"

    class Meta:
        abstract = True


class Like(Piece):
    target = models.ForeignKey(Piece, on_delete=models.CASCADE, related_name='likes')

    @staticmethod
    def user_like_piece(user, piece):
        if not piece or piece.__class__ not in [Collection]:
            return
        like = Like.objects.filter(owner=user, target=piece).first()
        if not like:
            like = Like.objects.create(owner=user, target=piece)
        return like


class Note(Content):
    pass


class Comment(Content):
    text = models.TextField(blank=False, null=False)

    @staticmethod
    def comment_item_by_user(item, user, text, visibility=0):
        comment = Comment.objects.filter(owner=user, item=item).first()
        if not text:
            if comment is not None:
                comment.delete()
                comment = None
        elif comment is None:
            comment = Comment.objects.create(owner=user, item=item, text=text, visibility=visibility)
        elif comment.text != text or comment.visibility != visibility:
            comment.text = text
            comment.visibility = visibility
            comment.save()
        return comment


class Review(Content):
    url_path = 'review'
    title = models.CharField(max_length=500, blank=False, null=False)
    body = MarkdownxField()

    @property
    def html_content(self):
        return mistune.html(self.body)

    @cached_property
    def rating_grade(self):
        return Rating.get_item_rating_by_user(self.item, self.owner)

    @ staticmethod
    def review_item_by_user(item, user, title, body, metadata={}, visibility=0):
        # allow multiple reviews per item per user.
        review = Review.objects.create(owner=user, item=item, title=title, body=body, metadata=metadata, visibility=visibility)
        """
        review = Review.objects.filter(owner=user, item=item).first()
        if title is None:
            if review is not None:
                review.delete()
                review = None
        elif review is None:
            review = Review.objects.create(owner=user, item=item, title=title, body=body, visibility=visibility)
        else:
            review.title = title
            review.body = body
            review.visibility = visibility
            review.save()
        """
        return review


class Rating(Content):
    grade = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(10), MinValueValidator(1)], null=True)

    @ staticmethod
    def get_rating_for_item(item):
        stat = Rating.objects.filter(item=item, grade__isnull=False).aggregate(average=Avg('grade'), count=Count('item'))
        return stat['average'] if stat['count'] >= 5 else None

    @ staticmethod
    def get_rating_count_for_item(item):
        stat = Rating.objects.filter(item=item, grade__isnull=False).aggregate(count=Count('item'))
        return stat['count']

    @ staticmethod
    def rate_item_by_user(item, user, rating_grade, visibility=0):
        if rating_grade and (rating_grade < 1 or rating_grade > 10):
            raise ValueError(f'Invalid rating grade: {rating_grade}')
        rating = Rating.objects.filter(owner=user, item=item).first()
        if not rating_grade:
            if rating:
                rating.delete()
                rating = None
        elif rating is None:
            rating = Rating.objects.create(owner=user, item=item, grade=rating_grade, visibility=visibility)
        elif rating.grade != rating_grade or rating.visibility != visibility:
            rating.visibility = visibility
            rating.grade = rating_grade
            rating.save()
        return rating

    @ staticmethod
    def get_item_rating_by_user(item, user):
        rating = Rating.objects.filter(owner=user, item=item).first()
        return rating.grade if rating else None


Item.rating = property(Rating.get_rating_for_item)
Item.rating_count = property(Rating.get_rating_count_for_item)


class Reply(Piece):
    reply_to_content = models.ForeignKey(Piece, on_delete=models.SET_NULL, related_name='replies', null=True)
    title = models.CharField(max_length=500, null=True)
    body = MarkdownxField()
    pass


"""
List (abstract class)
"""

list_add = django.dispatch.Signal()
list_remove = django.dispatch.Signal()


class List(Piece):
    class Meta:
        abstract = True

    _owner = models.ForeignKey(User, on_delete=models.PROTECT)  # duplicated owner field to make unique key possible for subclasses

    def save(self, *args, **kwargs):
        self._owner = self.owner
        super().save(*args, **kwargs)

    # MEMBER_CLASS = None  # subclass must override this
    # subclass must add this:
    # items = models.ManyToManyField(Item, through='ListMember')

    @property
    def ordered_members(self):
        return self.members.all().order_by('position', 'item_id')

    @property
    def ordered_items(self):
        return self.items.all().order_by(self.MEMBER_CLASS.__name__.lower() + '__position')

    @property
    def recent_items(self):
        return self.items.all().order_by('-' + self.MEMBER_CLASS.__name__.lower() + '__created_time')

    @property
    def recent_members(self):
        return self.members.all().order_by('-created_time')

    def has_item(self, item):
        return self.members.filter(item=item).count() > 0

    def append_item(self, item, **params):
        if item is None or self.has_item(item):
            return None
        else:
            ml = self.ordered_members
            p = {'parent': self}
            p.update(params)
            member = self.MEMBER_CLASS.objects.create(owner=self.owner, position=ml.last().position + 1 if ml.count() else 1, item=item, **p)
            list_add.send(sender=self.__class__, instance=self, item=item, member=member)
            return member

    def remove_item(self, item):
        member = self.members.all().filter(item=item).first()
        if member:
            list_remove.send(sender=self.__class__, instance=self, item=item, member=member)
            member.delete()

    def move_up_item(self, item):
        members = self.ordered_members
        member = members.filter(item=item).first()
        if member:
            other = members.filter(position__lt=member.position).last()
            if other:
                p = other.position
                other.position = member.position
                member.position = p
                other.save()
                member.save()

    def move_down_item(self, item):
        members = self.ordered_members
        member = members.filter(item=item).first()
        if member:
            other = members.filter(position__gt=member.position).first()
            if other:
                p = other.position
                other.position = member.position
                member.position = p
                other.save()
                member.save()


class ListMember(Piece):
    """
    ListMember - List class's member class
    It's an abstract class, subclass must add this:

    parent = models.ForeignKey('List', related_name='members', on_delete=models.CASCADE)
    """
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    position = models.PositiveIntegerField()

    @cached_property
    def mark(self):
        m = Mark(self.owner, self.item)
        m.shelfmember = self
        return m

    class Meta:
        abstract = True

    def __str__(self):
        return f'{self.id}:{self.position} ({self.item})'


"""
Shelf
"""


class ShelfType(models.TextChoices):
    WISHLIST = ('wishlist', '未开始')
    PROGRESS = ('progress', '进行中')
    COMPLETE = ('complete', '完成')
    # DISCARDED = ('discarded', '放弃')


ShelfTypeNames = [
    [ItemCategory.Book, ShelfType.WISHLIST, _('想读')],
    [ItemCategory.Book, ShelfType.PROGRESS, _('在读')],
    [ItemCategory.Book, ShelfType.COMPLETE, _('读过')],
    [ItemCategory.Movie, ShelfType.WISHLIST, _('想看')],
    [ItemCategory.Movie, ShelfType.PROGRESS, _('在看')],
    [ItemCategory.Movie, ShelfType.COMPLETE, _('看过')],
    [ItemCategory.TV, ShelfType.WISHLIST, _('想看')],
    [ItemCategory.TV, ShelfType.PROGRESS, _('在看')],
    [ItemCategory.TV, ShelfType.COMPLETE, _('看过')],
    [ItemCategory.Music, ShelfType.WISHLIST, _('想听')],
    [ItemCategory.Music, ShelfType.PROGRESS, _('在听')],
    [ItemCategory.Music, ShelfType.COMPLETE, _('听过')],
    [ItemCategory.Game, ShelfType.WISHLIST, _('想玩')],
    [ItemCategory.Game, ShelfType.PROGRESS, _('在玩')],
    [ItemCategory.Game, ShelfType.COMPLETE, _('玩过')],


]


class ShelfMember(ListMember):
    parent = models.ForeignKey('Shelf', related_name='members', on_delete=models.CASCADE)


class Shelf(List):
    class Meta:
        unique_together = [['_owner', 'item_category', 'shelf_type']]

    MEMBER_CLASS = ShelfMember
    items = models.ManyToManyField(Item, through='ShelfMember', related_name="+")
    item_category = models.CharField(choices=ItemCategory.choices, max_length=100, null=False, blank=False)
    shelf_type = models.CharField(choices=ShelfType.choices, max_length=100, null=False, blank=False)

    def __str__(self):
        return f'{self.id} {self.title}'

    @cached_property
    def item_category_label(self):
        return ItemCategory(self.item_category).label

    @cached_property
    def shelf_label(self):
        return next(iter([n[2] for n in iter(ShelfTypeNames) if n[0] == self.item_category and n[1] == self.shelf_type]), self.shelf_type)

    @cached_property
    def title(self):
        q = _("{shelf_label}的{item_category}").format(shelf_label=self.shelf_label, item_category=self.item_category_label)
        return q
        # return _("{user}'s {shelf_name}").format(user=self.owner.mastodon_username, shelf_name=q)


class ShelfLogEntry(models.Model):
    owner = models.ForeignKey(User, on_delete=models.PROTECT)
    shelf = models.ForeignKey(Shelf, on_delete=models.CASCADE, related_name='entries', null=True)  # None means removed from any shelf
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    timestamp = models.DateTimeField(default=timezone.now)  # this may later be changed by user
    metadata = models.JSONField(default=dict)
    created_time = models.DateTimeField(auto_now_add=True)
    edited_time = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.owner}:{self.shelf}:{self.item}:{self.metadata}'


class ShelfManager:
    """
    ShelfManager

    all shelf operations should go thru this class so that ShelfLogEntry can be properly populated
    ShelfLogEntry can later be modified if user wish to change history
    """

    def __init__(self, user):
        self.owner = user

    def initialize(self):
        for ic in ItemCategory:
            for qt in ShelfType:
                Shelf.objects.create(owner=self.owner, item_category=ic, shelf_type=qt)

    def _shelf_member_for_item(self, item):
        return ShelfMember.objects.filter(item=item, parent__in=self.owner.shelf_set.all()).first()

    def _shelf_for_item_and_type(item, shelf_type):
        if not item or not shelf_type:
            return None
        return self.owner.shelf_set.all().filter(item_category=item.category, shelf_type=shelf_type)

    def locate_item(self, item):
        member = ShelfMember.objects.filter(owner=self.owner, item=item).first()
        return member  # .parent if member else None

    def move_item(self, item, shelf_type, visibility=0, metadata=None):
        # shelf_type=None means remove from current shelf
        # metadata=None means no change
        if not item:
            raise ValueError('empty item')
        new_shelfmember = None
        last_shelfmember = self._shelf_member_for_item(item)
        last_shelf = last_shelfmember.parent if last_shelfmember else None
        last_metadata = last_shelfmember.metadata if last_shelfmember else None
        last_visibility = last_shelfmember.visibility if last_shelfmember else None
        shelf = self.get_shelf(item.category, shelf_type) if shelf_type else None
        changed = False
        if last_shelf != shelf:  # change shelf
            changed = True
            if last_shelf:
                last_shelf.remove_item(item)
            if shelf:
                new_shelfmember = shelf.append_item(item, visibility=visibility, metadata=metadata or {})
        elif last_shelf is None:
            raise ValueError('empty shelf')
        else:
            new_shelfmember = last_shelfmember
            if metadata is not None and metadata != last_metadata:  # change metadata
                changed = True
                last_shelfmember.metadata = metadata
                last_shelfmember.visibility = visibility
                last_shelfmember.save()
            elif visibility != last_visibility:  # change visibility
                last_shelfmember.visibility = visibility
                last_shelfmember.save()
        if changed:
            if metadata is None:
                metadata = last_metadata or {}
            ShelfLogEntry.objects.create(owner=self.owner, shelf=shelf, item=item, metadata=metadata)
        return new_shelfmember

    def get_log(self):
        return ShelfLogEntry.objects.filter(owner=self.owner).order_by('timestamp')

    def get_log_for_item(self, item):
        return ShelfLogEntry.objects.filter(owner=self.owner, item=item).order_by('timestamp')

    def get_shelf(self, item_category, shelf_type):
        return self.owner.shelf_set.all().filter(item_category=item_category, shelf_type=shelf_type).first()

    def get_items_on_shelf(self, item_category, shelf_type):
        shelf = self.owner.shelf_set.all().filter(item_category=item_category, shelf_type=shelf_type).first()
        return shelf.members.all().order_by

    @ staticmethod
    def get_manager_for_user(user):
        return ShelfManager(user)


User.shelf_manager = cached_property(ShelfManager.get_manager_for_user)
User.shelf_manager.__set_name__(User, 'shelf_manager')


"""
Collection
"""


class CollectionMember(ListMember):
    parent = models.ForeignKey('Collection', related_name='members', on_delete=models.CASCADE)

    @property
    def note(self):
        return self.metadata.get('comment')


class Collection(List):
    url_path = 'collection'
    MEMBER_CLASS = CollectionMember
    catalog_item = models.OneToOneField(CatalogCollection, on_delete=models.PROTECT)
    title = models.CharField(_("title in primary language"), max_length=1000, default="")
    brief = models.TextField(_("简介"), blank=True, default="")
    cover = models.ImageField(upload_to=item_cover_path, default=DEFAULT_ITEM_COVER, blank=True)
    items = models.ManyToManyField(Item, through='CollectionMember', related_name="collections")
    collaborative = models.PositiveSmallIntegerField(default=0)  # 0: Editable by owner only / 1: Editable by bi-direction followers

    @property
    def html(self):
        html = markdown(self.brief)
        return html

    @property
    def plain_description(self):
        html = markdown(self.brief)
        return RE_HTML_TAG.sub(' ', html)

    def save(self, *args, **kwargs):
        if getattr(self, 'catalog_item', None) is None:
            self.catalog_item = CatalogCollection()
        if self.catalog_item.title != self.title or self.catalog_item.brief != self.brief:
            self.catalog_item.title = self.title
            self.catalog_item.brief = self.brief
            self.catalog_item.cover = self.cover
            self.catalog_item.save()
        super().save(*args, **kwargs)


"""
Tag
"""


class TagMember(ListMember):
    parent = models.ForeignKey('Tag', related_name='members', on_delete=models.CASCADE)


TagValidators = [RegexValidator(regex=r'\s+', inverse_match=True)]


class Tag(List):
    MEMBER_CLASS = TagMember
    items = models.ManyToManyField(Item, through='TagMember')
    title = models.CharField(max_length=100, null=False, blank=False, validators=TagValidators)
    # TODO case convert and space removal on save
    # TODO check on save

    class Meta:
        unique_together = [['_owner', 'title']]

    @ staticmethod
    def cleanup_title(title):
        return title.strip().lower()


class TagManager:
    @ staticmethod
    def public_tags_for_item(item):
        tags = item.tag_set.all().filter(visibility=0).values('title').annotate(frequency=Count('owner')).order_by('-frequency')[: 20]
        return sorted(list(map(lambda t: t['title'], tags)))

    @ staticmethod
    def all_tags_for_user(user):
        tags = user.tag_set.all().values('title').annotate(frequency=Count('members__id')).order_by('-frequency')
        return list(map(lambda t: t['title'], tags))

    @ staticmethod
    def tag_item_by_user(item, user, tag_titles, default_visibility=0):
        titles = set([Tag.cleanup_title(tag_title) for tag_title in tag_titles])
        current_titles = set([m.parent.title for m in TagMember.objects.filter(owner=user, item=item)])
        for title in titles - current_titles:
            tag = Tag.objects.filter(owner=user, title=title).first()
            if not tag:
                tag = Tag.objects.create(owner=user, title=title, visibility=default_visibility)
            tag.append_item(item)
        for title in current_titles - titles:
            tag = Tag.objects.filter(owner=user, title=title).first()
            tag.remove_item(item)

    @ staticmethod
    def get_item_tags_by_user(item, user):
        current_titles = [m.parent.title for m in TagMember.objects.filter(owner=user, item=item)]
        return current_titles

    @ staticmethod
    def add_tag_by_user(item, tag_title, user, default_visibility=0):
        title = Tag.cleanup_title(tag_title)
        tag = Tag.objects.filter(owner=user, title=title).first()
        if not tag:
            tag = Tag.objects.create(owner=user, title=title, visibility=default_visibility)
        tag.append_item(item)

    @ staticmethod
    def get_manager_for_user(user):
        return TagManager(user)

    def __init__(self, user):
        self.owner = user

    @ property
    def all_tags(self):
        return TagManager.all_tags_for_user(self.owner)

    def add_item_tags(self, item, tags, visibility=0):
        for tag in tags:
            TagManager.add_tag_by_user(item, tag, self.owner, visibility)

    def get_item_tags(self, item):
        return sorted([m['parent__title'] for m in TagMember.objects.filter(parent__owner=self.owner, item=item).values('parent__title')])


Item.tags = property(TagManager.public_tags_for_item)
User.tags = property(TagManager.all_tags_for_user)
User.tag_manager = cached_property(TagManager.get_manager_for_user)
User.tag_manager.__set_name__(User, 'tag_manager')


class Mark:
    """ this mimics previous mark behaviour """

    def __init__(self, user, item):
        self.owner = user
        self.item = item

    @ cached_property
    def shelfmember(self):
        return self.owner.shelf_manager.locate_item(self.item)

    @ property
    def id(self):
        return self.shelfmember.id if self.shelfmember else None

    @ property
    def shelf(self):
        return self.shelfmember.parent if self.shelfmember else None

    @ property
    def shelf_type(self):
        return self.shelfmember.parent.shelf_type if self.shelfmember else None

    @ property
    def shelf_label(self):
        return self.shelfmember.parent.shelf_label if self.shelfmember else None

    @ property
    def created_time(self):
        return self.shelfmember.created_time if self.shelfmember else None

    @ property
    def metadata(self):
        return self.shelfmember.metadata if self.shelfmember else None

    @ property
    def visibility(self):
        return self.shelfmember.visibility if self.shelfmember else None

    @ cached_property
    def tags(self):
        return self.owner.tag_manager.get_item_tags(self.item)

    @ cached_property
    def rating(self):
        return Rating.get_item_rating_by_user(self.item, self.owner)

    @ cached_property
    def comment(self):
        return Comment.objects.filter(owner=self.owner, item=self.item).first()

    @ property
    def text(self):
        return self.comment.text if self.comment else None

    @ cached_property
    def review(self):
        return Review.objects.filter(owner=self.owner, item=self.item).first()

    def update(self, shelf_type, comment_text, rating_grade, visibility, metadata=None, created_time=None, share_to_mastodon=False):
        share = share_to_mastodon and shelf_type is not None and (shelf_type != self.shelf_type or comment_text != self.text or rating_grade != self.rating)
        if shelf_type != self.shelf_type or visibility != self.visibility:
            self.shelfmember = self.owner.shelf_manager.move_item(self.item, shelf_type, visibility=visibility, metadata=metadata)
            if self.shelfmember and created_time:
                self.shelfmember.created_time = created_time
                self.shelfmember.save()
        if comment_text != self.text or visibility != self.visibility:
            self.comment = Comment.comment_item_by_user(self.item, self.owner, comment_text, visibility)
        if rating_grade != self.rating or visibility != self.visibility:
            Rating.rate_item_by_user(self.item, self.owner, rating_grade, visibility)
            self.rating = rating_grade
        if share:
            # this is a bit hacky but let's keep it until move to implement ActivityPub,
            # by then, we'll just change this to boost
            from mastodon.api import share_mark
            self.shared_link = self.shelfmember.metadata.get('shared_link') if self.shelfmember.metadata else None
            self.translated_status = self.shelf_label
            self.save = lambda **args: None
            if not share_mark(self):
                raise ValueError("sharing failed")
            if not self.shelfmember.metadata:
                self.shelfmember.metadata = {}
            if self.shelfmember.metadata.get('shared_link') != self.shared_link:
                self.shelfmember.metadata['shared_link'] = self.shared_link
                self.shelfmember.save()

    def delete(self):
        self.update(None, None, None, 0)
