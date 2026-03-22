import unittest

class TestContainer(unittest.TestCase):

    def setUp(self):
        # Set up any necessary data or state before each test
        self.container = Container()

    def test_add_item(self):
        self.container.add_item('item1')
        self.assertIn('item1', self.container.items)

    def test_remove_item(self):
        self.container.add_item('item1')
        self.container.remove_item('item1')
        self.assertNotIn('item1', self.container.items)

    def test_container_size(self):
        self.container.add_item('item1')
        self.container.add_item('item2')
        self.assertEqual(len(self.container.items), 2)

class TestCommonUtilities(unittest.TestCase):

    def test_util_function(self):
        result = util_function(some_input)
        self.assertEqual(result, expected_output)

if __name__ == '__main__':
    unittest.main()